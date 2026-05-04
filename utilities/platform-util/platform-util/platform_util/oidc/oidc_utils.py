#
# Copyright (c) 2025-2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import json
import os
from pathlib import Path
import re
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

OIDC_LOGIN_TIMEOUT = 120

# Global cache for JWKS KeyJar
# Structure: {issuer_url: {'keyjar': KeyJar, 'expires_at': timestamp}}
_keyjar_cache = {}
_KEYJAR_CACHE_TTL = 3600  # 1 hour

def get_oidc_token(username):
    """This method gets the oidc token from the calling user's
    environment; i.e., the file pointed to by the KUBECONFIG
    environment variable, or if not specified, then ~/.kube/config

    First checks for a static user.token entry (preserves existing behaviour).
    If not found, checks for a user.exec block containing oidc-login get-token
    and invokes it as a subprocess to obtain the token.

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

    # First: look for static user.token (existing behaviour)
    for config_user in data['users']:
        if config_user.get('name') == username:
            user_block = config_user.get('user') or {}
            token = user_block.get('token')
            if token:
                return token

    # Second: look for any user with an oidc-login exec block
    oidc_exec_blocks = []
    for config_user in data['users']:
        user = config_user.get('user', {})
        if not user:
            continue
        exec_block = user.get('exec')
        if exec_block and _is_oidc_login_exec(exec_block):
            oidc_exec_blocks.append(exec_block)

    if len(oidc_exec_blocks) > 1:
        LOG.error("Config error in kubeconfig file: multiple user "
                  "entries have oidc-login exec block. "
                  "Only one is expected.")
        return None

    if oidc_exec_blocks:
        token = _get_token_from_oidc_login(oidc_exec_blocks[0])
        if token:
            return token

    return None


def _is_oidc_login_exec(exec_block):
    """Check if an exec block is an oidc-login get-token command."""
    args = exec_block.get('args', [])
    return 'oidc-login' in args and 'get-token' in args


def _get_token_from_oidc_login(exec_block):
    """Invoke the oidc-login exec command and parse the ExecCredential response.

    Args:
        exec_block(dict): the exec block from kubeconfig user entry

    Returns: str of the ID token, or None on failure
    """
    command = exec_block.get('command')
    args = exec_block.get('args', [])
    if not command:
        LOG.error("oidc-login exec block has no command")
        return None

    cmd = [command] + args

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=None,
            stdin=None,
            timeout=OIDC_LOGIN_TIMEOUT
        )
    except FileNotFoundError:
        LOG.error("Command not found: %s. Ensure kubectl and "
                  "oidc-login plugin are installed.", command)
        return None
    except subprocess.TimeoutExpired:
        LOG.error("oidc-login command timed out after %d seconds",
                  OIDC_LOGIN_TIMEOUT)
        return None

    if result.returncode != 0:
        LOG.error("oidc-login command failed (rc=%d)", result.returncode)
        return None

    try:
        exec_credential = json.loads(result.stdout)
        token = exec_credential['status']['token']
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        LOG.error("Failed to parse ExecCredential response: %s", e)
        return None

    return token


def get_oidc_token_claims(oidc_token):
    """Validate OIDC token and return token dict & claims.
    Args:
        oidc_token (str): the oidc token to validate

    Returns: str of the dex token, or None if unable to get token
    """

    # Get oidc configs
    try:
        oidc_config = get_apiserver_oidc_args()
    except Exception as e:
        raise ValueError(str(e))

    if not oidc_config:
        msg = ('Failed to get OIDC config from kubernetes')
        LOG.error(msg)
        raise ValueError(msg)

    issuer_url = oidc_config.get('oidc-issuer-url')
    client_id = oidc_config.get('oidc-client-id')
    username_claim = oidc_config.get('oidc-username-claim')
    group_claim = oidc_config.get('oidc-groups-claim')

    # Validate token
    try:
        oidc_token_dict = validate_oidc_token(
            oidc_token,
            issuer_url,
            client_id
        )
    except Exception as e:
        raise ValueError(str(e))

    if not oidc_token_dict:
        msg = ('Failed OIDC validation for token details')
        LOG.error(msg)
        raise ValueError(msg)

    return {
        'token_dict': oidc_token_dict,
        'username_claim': username_claim,
        'group_claim': group_claim}


def parse_oidc_token_claims(claims, domain, project):
    """Parse OIDC token claims and return username and roles.
    Args:
        claims (dict): the oidc token claims to parse
        domain (str): the keystone domain
        project (str): the keystone project
    Returns: dict with 'username' and 'roles' keys
    """
    # Get username
    try:
        username = get_username_from_oidc_token(
            claims['token_dict'], claims['username_claim'])
    except Exception as e:
        msg = ('Failed to extract username from OIDC token: %s') % e
        LOG.error(msg)
        raise ValueError(msg)

    if not username:
        msg = ('Invalid username for the OIDC token')
        LOG.error(msg)
        raise ValueError(msg)

    # Get roles
    try:
        roles = get_keystone_roles_for_oidc_token(
            claims['token_dict'],
            claims['username_claim'], claims['group_claim'],
            domain=domain, project=project)
    except Exception as e:
        msg = ('Failed to get roles from OIDC token: %s') % e
        LOG.error(msg)
        raise ValueError(msg)

    if not roles:
        msg = ('Invalid roles for the OIDC token')
        LOG.error(msg)
        raise ValueError(msg)

    LOG.debug("OIDC authentication successful for user %s with roles %s",
              username, roles)
    return {'username': username, 'roles': roles}


def _get_keyjar(issuer_url, client_id, force_refresh=False):
    """Get or refresh the cached KeyJar for the given issuer.

    Args:
        issuer_url (str): the url of the issuer of the oidc token (dex)
        client_id (str): the client id for connecting to oidc identity provider
        force_refresh (bool): force refresh even if cache is valid

    Returns: KeyJar object or None if unable to fetch
    """
    current_time = time.time()

    # Check if we have a valid cached KeyJar
    if not force_refresh and issuer_url in _keyjar_cache:
        cached = _keyjar_cache[issuer_url]
        if cached['expires_at'] > current_time:
            return cached['keyjar']

    # Fetch new JWKS
    try:
        client = Client(client_id=client_id)
        provider_info = client.provider_config(issuer_url)
        jwks_uri = provider_info["jwks_uri"]
        keys = requests.get(jwks_uri).json()

        keyjar = KeyJar()
        keyjar.import_jwks(keys, issuer_url)

        # Cache the KeyJar
        _keyjar_cache[issuer_url] = {
            'keyjar': keyjar,
            'expires_at': current_time + _KEYJAR_CACHE_TTL
        }

        return keyjar
    except Exception as e:
        LOG.error(f"Failed to fetch JWKS from {issuer_url}: {e}")
        return None


def validate_oidc_token(token, issuer_url, client_id):
    """ This method validates a given oidc token

    Args:
        token (str): the oidc token to validate
        issuer_url (str): the url of the issuer of the oidc token (dex)
        client_id (str): the client id for connecting to oidc identity provider
    Returns: dict representation of the token, or None if validation failed
    """

    # Get cached KeyJar
    keyjar = _get_keyjar(issuer_url, client_id)
    if not keyjar:
        return None

    try:
        # Validate token
        id_token = IdToken().from_jwt(token, keyjar=keyjar, sender=issuer_url)
        token_claims = id_token.to_dict()

        # Check if token is expired
        current_time_seconds = time.time()
        if token_claims['exp'] < current_time_seconds:
            LOG.warning("Token expired during validation")
            return None

        return token_claims
    # this is just a verification failure, either due to expiration or
    # because the token is from another system. no need to log anything
    except jwkest.jws.NoSuitableSigningKeys:
        # Try refreshing the KeyJar once in case keys were rotated
        keyjar = _get_keyjar(issuer_url, client_id, force_refresh=True)
        if keyjar:
            try:
                id_token = IdToken().from_jwt(token, keyjar=keyjar, sender=issuer_url)
                token_claims = id_token.to_dict()

                current_time_seconds = time.time()
                if token_claims['exp'] < current_time_seconds:
                    LOG.warning("Token expired during validation")
                    return None

                return token_claims
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
           '-n', 'kube-system', '-o', 'jsonpath={.data.ClusterConfiguration}'
           ]

    oidc_param_keys = ['oidc-issuer-url', 'oidc-client-id',
                       'oidc-groups-claim', 'oidc-username-claim']
    oidc_parameters = {}

    kubeadm_config_output = subprocess.run(cmd, capture_output=True)

    try:
        yaml_content = kubeadm_config_output.stdout.decode('utf-8')

        def quote_ipv6(match):
            full_match = match.group(0)

            # Skip if this is part of a URL - check if :// appears before [
            match_start = match.start()
            check_start = max(0, match_start - 10)
            before_match = yaml_content[check_start:match_start]
            if '://' in before_match:
                return full_match

            content = match.group(1)
            items = []
            current = ''
            in_quotes = None
            for char in content:
                if char in ('"', "'") and (not in_quotes or in_quotes == char):
                    in_quotes = None if in_quotes else char
                    current += char
                elif char == ',' and not in_quotes:
                    if current.strip():
                        items.append(current.strip())
                    current = ''
                else:
                    current += char
            if current.strip():
                items.append(current.strip())

            quoted = []
            for item in items:
                if ':' in item and not item.startswith('"') and not item.startswith("'"):
                    quoted.append(f'"{item}"')
                else:
                    quoted.append(item)
            return '[' + ', '.join(quoted) + ']'

        # Find and modify all arrays containing colons
        yaml_content = re.sub(r'\[([^\]]*:[^\]]*)\]', quote_ipv6, yaml_content)
        kubeadm_config = yaml.safe_load(yaml_content)
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
                roles.append(current_rolebinding_roles[-1])
            if user_or_group == username:
                roles.append(current_rolebinding_roles[-1])
    return list(set([s.strip() for s in roles]))
