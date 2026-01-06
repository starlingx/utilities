#
# Copyright (c) 2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import os
from pathlib import Path
import subprocess
import time

import jwkest
from oic.exception import MessageException
from oic.oic import Client
from oic.oic.message import AuthorizationResponse
from oic.oic.message import IdToken
from oic.oic.message import ProviderConfigurationResponse
from oic.utils.jwt import JWT
from oic.utils.keyio import KeyJar
from oslo_log import log
import requests
import yaml

LOG = log.getLogger(__name__)

def get_oidc_token(username):
    """This method gets the oidc token from the calling user's
    environment; i.e., the file pointed to by the KUBECONFIG
    environment variable, or if not specified, then ~/.kube/config

    Args:
        username(str): the name of the user to get the token for

    Returns: str of the dex token, or None if unable to get token 
    """

    kubeconfig_path = os.environ.get("KUBECONFIG")
    if kubeconfig_path is None:
        kubeconfig_path = str(Path.home()) + '/.kube/config'

    if not os.path.exists(kubeconfig_path):
        return None

    with open(kubeconfig_path, 'r') as f:
        data = yaml.safe_load(f)

    if 'users' not in data:
        return None

    for config_user in data['users']:
        if 'name' not in config_user:
            continue
        if config_user['name'] != username:
            continue
        try:
            return config_user['user']['token']
        except KeyError:
            return None

    return None


def validate_oidc_token(token, token_cache, issuer_url, client_id, cache_size=5000):
    """ This method validates a given oidc token
    It then updates the cache accordingly
    If the token validation is successful, the token is added to the cache
    Expired tokens in the cache are removed

    Args:
        token (str): the oidc token to validate
        cache (dict str:str): a cache of tokens:expire time
        issuer_url (str): the url of the issuer of the oidc token (dex)
        client_id (str): the client id for connecting to oidc identity provider
    Returns: dict representation of the token, or None if validation failed
    """

    # First check if token is in cache
    if (token in token_cache and
       token_cache[token]['exp'] > time.time()):
        return token_cache[token]

    try:
        # Initialize OIDC client
        client = Client(client_id=client_id)
        provider_info = client.provider_config(issuer_url)

        # Fetch public keys for verifying tokens
        jwks_uri = provider_info["jwks_uri"]
        keys = requests.get(jwks_uri).json()
        keyjar = KeyJar()
        keyjar.import_jwks(keys, issuer_url)

        # Validate token
        id_token = IdToken().from_jwt(token, keyjar=keyjar, sender=issuer_url)
        token_claims = id_token.to_dict()

        # adjust token cache
        current_time_seconds = time.time()
        oldest_exp_time = current_time_seconds
        oldest_token = None
        expired_tokens = []
        for cached_token, cached_token_claims in token_cache.items():
            if (oldest_token is None or
               cached_token_claims['exp'] < oldest_exp_time):
                oldest_exp_time = cached_token_claims['exp']
                oldest_token = cached_token
            if cached_token_claims['exp'] < current_time_seconds:
                expired_tokens.append(cached_token)
        for expired_token in expired_tokens:
            del token_cache[expired_token]
        if len(token_cache) >= cache_size:
            del token_cache[oldest_token]
        # add our new verified token to the cache
        token_cache[token] = token_claims

        return token_claims
    # this is just a verification failure, either due to expiration or
    # because the token is from another system. no need to log anything
    except jwkest.jws.NoSuitableSigningKeys:
        pass
    # could be a lot of other cases where it fails, ex dex temporarily
    # unreachable. We dont want whatever calling the common library to fail
    # due to this, so we just catch and return None for "token verify failed"
    except Exception as e:
        LOG.error({e})
    return None


def get_apiserver_oidc_args():
    """ This method gets the kube-apiserver parameters for oidc auth
    from the kubeadm config file

    Returns: dict of the apiserver parameters, None if they are not configured
    """
    cmd = ['kubectl', '--kubeconfig', '/etc/kubernetes/admin.conf',
           'get', 'configmap', 'kubeadm-config',
           '-n', 'kube-system', '-o', 'yaml'
           ]

    oidc_param_keys = ['oidc-issuer-url', 'oidc-client-id',
                       'oidc-groups-claim', 'oidc-username-claim']
    oidc_parameters = {}

    kubeadm_config_output = subprocess.run(cmd, capture_output=True)
    kubeadm_config = yaml.safe_load(kubeadm_config_output.stdout)

    try:
        kubeadm_config = yaml.safe_load(
            kubeadm_config['data']['ClusterConfiguration']
        )
        for extraArg in kubeadm_config['apiServer']['extraArgs']:
            if extraArg['name'] in oidc_param_keys:
                oidc_parameters[extraArg['name']] = extraArg['value']
    except KeyError:
        return None

    # we have error checking for kube-apiserver oidc parameters
    # all 4 in oidc_param_keys should be present, or none at all
    # but just in case the system somehow got in a state where some
    # are present and some are not, respond as if none are present,
    # since that's an invalid config
    if len(oidc_parameters) != 4:
        return None

    return oidc_parameters


def get_username_from_oidc_token(token, username_claim):
    """ This method gets the username from an oidc token

    Args:
        token (dict): a dict representation of the oidc token
        username_claim(str): username claim, see get_apiserver_oidc_args
    """
    return token.get(username_claim)


def get_keystone_roles_for_oidc_token(token, username_claim, group_claim,
                                      domain='Default', project='admin'):
    """ This method gets the keystone roles, within a specific domain and
    project, bound to the user and/or group(s) in the oidc token.

    The role bindings are configured through service parameters
    This list of roles can then be used with oslo policy to do authorization
    Note that only Default domain and admin project will be supported for now

    Args:
        token (dict): a dict representation of the oidc token
        username_claim(str): username claim, see get_apiserver_oidc_args
        group_claim(str): group claim, see get_apiserver_oidc_args
        domain (str): The domain of the resource being accessed
        project (str): The project of the resource being accessed

    Returns: Str list of keystone role bound to the user and/or groups
             in the oidc token.
    """

    username = get_username_from_oidc_token(token, username_claim)
    groups = token.get(group_claim)
    roles = []
    rolebinding_config_path = '/etc/platform/.rolebindings.conf'
    with open(rolebinding_config_path, 'r') as f:
        rolebindings = f.read()

    if rolebindings is None or rolebindings == '' or rolebindings.isspace():
        return roles

    # the file contains multiple entries, separated by ;
    rolebindings = rolebindings.split(';')
    for rolebinding in rolebindings:
        # each entry contains comma separated users and groups, followed by :
        # then comma separated roles
        rolebinding = rolebinding.split(':')
        current_users_and_groups = rolebinding[0].split(',')
        current_rolebinding_roles = rolebinding[1].split(',')

        for user_or_group in current_users_and_groups:
            # groups start with a %
            if (user_or_group[0] == '%' and groups is not None and
               user_or_group[1:] in groups):
                roles.extend(current_rolebinding_roles)
            if user_or_group == username:
                roles.extend(current_rolebinding_roles)
    return list(set([s.strip() for s in roles]))
