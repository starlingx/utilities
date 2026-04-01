#
# Copyright (c) 2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import base64
import json
import logging
import subprocess
import time

from kubernetes import client
from kubernetes import config
import requests

from cephclient import exception

CEPH_DASHBOARD_USER = 'admin'
CEPH_DASHBOARD_SERVICE = 'dashboard'
CEPH_GET_SERVICE_RETRY_COUNT = 15
CEPH_CLIENT_RETRY_TIMEOUT_SEC = 5
CEPH_CLI_TIMEOUT_SEC = 15

LOG = logging.getLogger('rook_ceph_client')
LOG.setLevel(logging.INFO)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch.setFormatter(logging.Formatter(
    '%(asctime)s %(levelname)s %(name)s %(message)s'))
LOG.addHandler(ch)

class RookCephClient(object):
    """Client for connecting to Rook Ceph Dashboard API"""

    def __init__(self, username=CEPH_DASHBOARD_USER, password=None, verify=False):
        self.username = username
        self.password = password
        self.service_url = None
        self.session = None
        self.verify = verify

    def _get_dashboard_password(self):
        """Fetch Rook Ceph dashboard password from Kubernetes secret"""
        try:
            try:
                config.load_incluster_config()
            except config.ConfigException:
                config.load_kube_config("/etc/kubernetes/admin.conf")

            v1 = client.CoreV1Api()
            secret_obj = v1.read_namespaced_secret(
                name='rook-ceph-dashboard-password',
                namespace='rook-ceph'
            )
            secret = secret_obj.data['password']
            return base64.b64decode(secret).decode().strip()
        except Exception as e:
            raise exception.RookCephClientException(f"Failed to retrieve dashboard password: {e}")

    def _get_service_url(self):
        """Retrieve the Ceph Dashboard service URL via 'ceph mgr services', retrying if unavailable."""
        attempts = 1

        status = {}

        while attempts <= CEPH_GET_SERVICE_RETRY_COUNT:
            try:
                output = subprocess.check_output(
                    'ceph mgr services',
                    timeout=CEPH_CLI_TIMEOUT_SEC,
                    shell=True)
            except subprocess.CalledProcessError as e:
                raise exception.CephMgrDumpError(str(e))
            except subprocess.TimeoutExpired as e:
                raise exception.CephCliTimeoutExpired(str(e))
            try:
                status = json.loads(output)
                if not status:
                    LOG.info("Unable to get service url")
                    time.sleep(CEPH_CLIENT_RETRY_TIMEOUT_SEC)
                    attempts += 1
                    continue
            except (KeyError, ValueError):
                raise exception.CephMgrJsonError(output)
            LOG.info("Service url retrieved successfully")
            break
        else:
            raise exception.RookCephClientException(
                f"Unable to get service url after "
                f"{CEPH_GET_SERVICE_RETRY_COUNT} attempts")

        service_url = status.get(CEPH_DASHBOARD_SERVICE, {})
        if not service_url:
            raise exception.RookCephClientException("Dashboard Module is not available. "
                                                    f"Available services: {', '.join(status.keys())}")
        return service_url

    def _ensure_connected(self, force=False):
        """Lazily initialize connection on first use, or re-initialize if forced"""
        if self.session is not None and not force:
            return
        self.session = None
        self.password = self._get_dashboard_password()
        self.service_url = self._get_service_url().rstrip("/")
        self._init_session()

    def _init_session(self):
        """Initialize session and authenticate to get JWT token"""
        self.session = requests.Session()
        self.session.headers['accept'] = 'application/vnd.ceph.api.v1.0+json'
        self.session.headers['Content-Type'] = 'application/json'
        if self.service_url and self.username and self.password:
            self._authenticate()
        else:
            LOG.warning('No credentials provided, skipping authentication')

    def _authenticate(self):
        """Authenticate and store JWT token in session headers"""
        url = f"{self.service_url}/api/auth"
        LOG.info('Authenticating to Rook Ceph Dashboard as user \'%s\'', self.username)
        try:
            response = self.session.post(
                url,
                data=json.dumps({'username': self.username, 'password': self.password}),
                verify=self.verify,
            )
            response.raise_for_status()
            token = response.json()['token']
            self.session.headers['Authorization'] = f'Bearer {token}'
            LOG.info('Authentication successful')
        except (requests.RequestException, KeyError) as e:
            LOG.warning('Authentication failed: %s', e)
            raise exception.RookCephClientException(f"Authentication failed: {e}")

    def _summarize(self, data, depth=2):
        """Recursively summarize a JSON structure, removing empty values and considering depth level"""

        if not isinstance(data, (dict, list)):
            return data
        if isinstance(data, list):
            if depth == 0:
                return len(data)
            if data and isinstance(data[0], dict):
                return [self._summarize(data[0], depth - 1), f'...+{len(data) - 1}']
            return len(data)

        # filter empty values at every dict level before recursing
        filtered = {k: v for k, v in data.items() if v is not None and v != '' and v != [] and v != {}}
        if depth == 0:
            return list(filtered.keys())

        return {k: self._summarize(v, depth - 1) for k, v in filtered.items()}

    def _request(self, method, endpoint, **kwargs):
        """Make HTTP request to Dashboard API"""
        self._ensure_connected()
        url = f"{self.service_url}/api/{endpoint.lstrip('/')}"
        kwargs.setdefault('verify', self.verify)
        LOG.info('Request params: url=%s, method=%s', url, method)
        for attempt in range(1, 4):
            try:
                response = self.session.request(method, url, **kwargs)
                response.raise_for_status()
                result = response.json() if response.content else {}
                if LOG.isEnabledFor(logging.DEBUG):
                    LOG.debug('Result raw: %s', json.dumps(result, separators=(',', ':')))
                else:
                    LOG.info('Result: %s bytes, structure: %s', len(response.content),
                            self._summarize(result, depth=2))
                return response, result
            except requests.RequestException as e:
                if attempt >= 3:
                    LOG.warning('Request error (max retries reached): %s', e)
                    raise exception.RookCephClientException(str(e))
                LOG.warning('Request error: %s, reconnecting... (attempt %d/3)', e, attempt)
                self._ensure_connected(force=True)

    def health_minimal(self, body='json', timeout=None):
        """Return minimal cluster health summary from the Dashboard API."""
        response, data = self._request('GET', 'health/minimal', timeout=timeout)
        return response, {'status': 'OK', 'output': data}

    def health_full(self, body='json', timeout=None):
        """Return full cluster health details from the Dashboard API."""
        response, data = self._request('GET', 'health/full', timeout=timeout)
        return response, {'status': 'OK', 'output': data}

    def get_cluster_fsid(self, body='json', timeout=None):
        """Return the cluster FSID/UUID from the Dashboard API."""
        response, data = self._request('GET', 'health/get_cluster_fsid', timeout=timeout)
        return response, {'status': 'OK', 'output': data}

    def monitor(self, body='json', timeout=None):
        """Return Monitor daemon statistics from the Dashboard API."""
        response, data = self._request('GET', 'monitor', timeout=timeout)
        return response, {'status': 'OK', 'output': data}

    def osd(self, body='json', timeout=None):
        """Return OSD statistics from the Dashboard API."""
        response, data = self._request('GET', 'osd', timeout=timeout)
        return response, {'status': 'OK', 'output': data}
