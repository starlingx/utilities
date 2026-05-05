#
# Copyright (c) 2019,2026 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

import os
import threading

from kubernetes import client
from kubernetes import config
import six

from cephclient.client import CephClient
from cephclient.exception import CephClientFunctionNotImplemented
from cephclient.exception import CephClientInvalidOsdIdValue
from cephclient.exception import CephClientTypeError
from cephclient.exception import RookCephClientException
from cephclient.rook_client import RookCephClient


class BareMetalCephWrapper(CephClient):

    def __init__(self, endpoint=''):
        super(BareMetalCephWrapper, self).__init__()

    def auth_import(self, body='json', timeout=None):
        raise CephClientFunctionNotImplemented(name='auth_import')

    def _sanitize_osdid_to_str(self, _id):
        if isinstance(_id, six.string_types):
            prefix = 'osd.'
            if not _id.startswith(prefix):
                try:
                    int(_id)
                except ValueError:
                    raise CephClientInvalidOsdIdValue(
                        osdid=_id)
                _id = prefix + _id
        elif isinstance(_id, six.integer_types):
            _id = 'osd.{}'.format(_id)
        else:
            raise CephClientInvalidOsdIdValue(
                osdid=_id)
        return _id

    def _sanitize_osdid_to_int(self, _id):
        if isinstance(_id, six.string_types):
            prefix = 'osd.'
            if _id.startswith(prefix):
                _id = _id[len(prefix):]
            try:
                _id = int(_id)
            except ValueError:
                raise CephClientInvalidOsdIdValue(
                    osdid=_id)
        elif not isinstance(_id, six.integer_types):
            raise CephClientInvalidOsdIdValue(
                osdid=_id)
        return _id

    def osd_create(self, uuid, body='json', timeout=None, params=None):
        """create new osd (with optional UUID and ID)

        Notes:
        1. osd create declares it accepts osd id as string but only works when
           given an integer value; it automatically generates an ID otherwise
           instead of using the one provided by 'osd create id=...'

        2. old cephclient passes osd id through params dictionary
        """
        kwargs = dict(uuid=uuid, body=body, timeout=timeout)
        try:
            kwargs['id'] = self._sanitize_osdid_to_int(params['id'])
        except (KeyError, TypeError):
            pass
        return self._request('osd create', **kwargs)

    def osd_rm(self, ids, body='json', timeout=None):
        """remove osd(s) <id> [<id>...], or use <any|all> to remove all osds
        """
        if isinstance(ids, list):
            ids = [self._sanitize_osdid_to_str(_id)
                   for _id in ids]
        else:
            ids = self._sanitize_osdid_to_str(ids)
        return super(BareMetalCephWrapper, self).osd_rm(
            ids=ids, body=body, timeout=timeout)

    def osd_remove(self, ids, body='json', timeout=None):
        return self.osd_rm(ids, body=body, timeout=timeout)

    def osd_down(self, ids, body='json', timeout=None):
        """set osd(s) <id> [<id>...] down, or use <any|all> to set all osds down
        """
        if isinstance(ids, list):
            ids = [self._sanitize_osdid_to_str(_id)
                   for _id in ids]
        else:
            ids = self._sanitize_osdid_to_str(ids)
        return super(BareMetalCephWrapper, self).osd_down(
            ids=ids, body=body, timeout=timeout)

    OSD_CRUSH_TREE_CONVERTED_FIELDS = [
        'crush_weight', 'depth', 'id', 'name', 'type', 'type_id']

    def _osd_crush_tree_convert_node(self, node):
        return {k: node[k] for k in self.OSD_CRUSH_TREE_CONVERTED_FIELDS
                if k in node}

    def _osd_crush_tree_populate_tree(self, node, node_map):
        children = node.get('children')
        node = self._osd_crush_tree_convert_node(node)
        if node['type'] != 'osd':
            node['items'] = []
            for _id in children:
                node['items'].append(
                    self._osd_crush_tree_populate_tree(
                        node_map[_id], node_map))
        return node

    def osd_crush_tree(self, shadow=None, body='json', timeout=None):
        """dump crush buckets and items in a tree view """
        response, _body = super(BareMetalCephWrapper, self).osd_crush_tree(
            shadow=shadow, body=body, timeout=timeout)
        trees = []
        if response.ok and body == 'json' \
           and 'output' in _body:
            node_map = {}
            root_nodes = []
            nodes = _body['output']['nodes']
            for node in nodes:
                node_map[node['id']] = node
                if node['type'] == 'root':
                    root_nodes.append(node)
            for root in root_nodes:
                trees.append(
                    self._osd_crush_tree_populate_tree(
                        root, node_map))
            _body['output'] = trees
        return response, _body

    def _osd_crush_rule_by_ruleset(self, ruleset, timeout=None):
        response, _body = self.osd_crush_rule_dump(
            body='json', timeout=timeout)
        if not response.ok:
            return response, _body
        name = None
        for rule in _body['output']:
            if rule.get('ruleset') == ruleset:
                name = rule.get('rule_name')
        _body['output'] = dict(rule=name)
        return response, _body

    def _osd_crush_ruleset_by_rule(self, rule, timeout=None):
        response, _body = self.osd_crush_rule_dump(
            name=rule, body='json', timeout=timeout)
        return response, _body

    def osd_pool_create(self, pool, pg_num, pgp_num=None, pool_type=None,
                        erasure_code_profile=None, ruleset=None,
                        expected_num_objects=None, body='json', timeout=None):
        """create pool

        Notes:
        1. map 'ruleset' to 'rule' (assuming 1:1 correspondence)
        """
        response, _body = self._osd_crush_rule_by_ruleset(ruleset)
        if not response.ok:
            return response, _body
        rule = _body['output']['rule']
        return super(BareMetalCephWrapper, self).osd_pool_create(
            pool, pg_num, pgp_num=pgp_num, pool_type=pool_type,
            erasure_code_profile=erasure_code_profile, rule=rule,
            expected_num_objects=expected_num_objects, body=body,
            timeout=timeout)

    def osd_get_pool_param(self, pool, var, body='json', timeout=None):
        """get pool parameter <var> """
        if var == 'crush_ruleset':
            response, _body = super(BareMetalCephWrapper, self).osd_pool_get(
                pool, 'crush_rule', body='json', timeout=timeout)
            if response.ok:
                rule = _body['output']['crush_rule']
                del _body['output']['crush_rule']
                response, _body = self._osd_crush_ruleset_by_rule(
                    rule, timeout=timeout)
                if response.ok:
                    _body['output'] = dict(
                        crush_ruleset=_body['output']['ruleset'])
            return response, _body
        else:
            return super(BareMetalCephWrapper, self).osd_pool_get(
                pool, var, body=body, timeout=timeout)

    def osd_pool_set(self, pool, var, val, force=None,
                     body='json', timeout=None):
        """set pool parameter <var> to <val> """
        return super(BareMetalCephWrapper, self).osd_pool_set(
            pool=pool, var=var, val=str(val),
            force=force, body=body, timeout=timeout)

    def osd_set_pool_param(self, pool, var, val, force=None,
                           body='json', timeout=None):
        """set pool parameter <var> to <val> """
        if var == 'crush_ruleset':
            var = 'crush_rule'
            response, _body = self._osd_crush_rule_by_ruleset(
                val, timeout=timeout)
            if not response.ok:
                return response, _body
            val = _body['output']['rule']
        return super(BareMetalCephWrapper, self).osd_pool_set(
            pool, var, str(val), force=None,
            body=body, timeout=timeout)

    def _auth_convert_caps(self, caps):
        if caps:
            if not isinstance(caps, dict):
                raise CephClientTypeError(
                    name='caps',
                    actual=type(caps),
                    expected=dict)
            _caps = []
            for key, value in list(caps.items()):
                _caps.append(key)
                _caps.append(value)
            caps = _caps
        return caps

    def auth_add(self, entity, caps=None, body='json', timeout=None):
        """Add auth info

        Adds auth info for <entity> from input file, or random key if no input
        is given, and/or any caps specified in the command
        """
        caps = self._auth_convert_caps(caps)
        return super(BareMetalCephWrapper, self).auth_add(
            entity, caps=caps, body=body, timeout=timeout)

    def auth_caps(self, entity, caps, body='json', timeout=None):
        """update caps for <name> from caps specified in the command """
        caps = self._auth_convert_caps(caps)
        return super(BareMetalCephWrapper, self).auth_caps(
            entity, caps=caps, body=body, timeout=timeout)

    def auth_get_or_create(self, entity, caps=None, body='json', timeout=None):
        """Get or create auth info

        Adds auth info for <entity> from input file, or random key if no input
        given, and/or any caps specified in the command
        """
        caps = self._auth_convert_caps(caps)
        return super(BareMetalCephWrapper, self).auth_get_or_create(
            entity, caps, body=body, timeout=timeout)

    def auth_get_or_create_key(self, entity, caps=None,
                               body='json', timeout=None):
        """Get or add auth key

        Gets, or adds, key for <name> from system/caps pairs specified in the
        command.  If key already exists, any given caps must match the
        existing caps for that key.
        """
        caps = self._auth_convert_caps(caps)
        response, _body = super(BareMetalCephWrapper, self).auth_get_or_create_key(
            entity, caps, body=body, timeout=timeout)
        if response.ok:
            _body['output'] = _body['output']
        return response, _body

    def osd_set_key(self, key, sure=None, body='json', timeout=None):
        """set <key> """
        return self.osd_set(key, sure=sure, body=body, timeout=timeout)


class RookCephWrapper(RookCephClient):

    def _build_response(self, output):
        return {"output": output}

    def health(self, detail=None, body='json', timeout=None):
        response, body_data = self.health_minimal(timeout=timeout)
        health = body_data.get("output", {}).get("health", {})
        response_body = {
            "status": health.get("status"),
            "checks": health.get("checks"),
            "mutes":  health.get("mutes"),
        }
        if body == 'json':
            return response, self._build_response(response_body)
        return response, health.get("status")

    def fsid(self, body='json', timeout=None):
        response, body_data = self.get_cluster_fsid(timeout=timeout)
        fsid_value = body_data.get("output", {})
        if body == 'json':
            response_body = {
                "fsid": fsid_value
            }
            return response, self._build_response(response_body)
        return response, fsid_value

    def status(self, body='json', timeout=None):
        response, body_data = self.health_full(timeout=timeout)
        data     = body_data.get("output", {})
        df_stats = data.get("df", {}).get("stats", {})
        pgmap    = dict(data.get("client_perf", {}))
        pgmap["bytes_total"] = df_stats.get("total_bytes", 0)
        pgmap["bytes_used"]  = df_stats.get("total_used_raw_bytes", 0)
        pgmap["bytes_avail"] = df_stats.get("total_avail_bytes", 0)
        response_body = {
            "health": {"status": data.get("health", {}).get("status")},
            "pgmap": pgmap,
        }
        return response, self._build_response(response_body)

    def df(self, body='json', timeout=None):
        response, body_data = self.health_minimal(timeout=timeout)
        stats = body_data.get("output", {}).get("df", {}).get("stats", {})
        stats["total_used_bytes"] = stats.get("total_used_raw_bytes", 0)
        response_body = {
            "stats": stats
        }
        return response, self._build_response(response_body)

    def mon_dump(self, body='json', timeout=None):
        response, body_data = self.monitor(timeout=timeout)
        mon_status = body_data.get("output", {}).get("mon_status", {})
        monmap = mon_status.get("monmap", {})
        quorum = [m.get("rank") for m in mon_status.get("in_quorum", [])]
        response_body = {
            "mons": monmap.get("mons", []),
            "quorum": quorum,
        }
        return response, self._build_response(response_body)

    def osd_tree(self, body='json', timeout=None):
        response, body_data = self.health_full(timeout=timeout)
        tree = body_data.get("output", {}).get("osd_map", {}).get("tree", {})
        response_body = {
            "nodes": tree.get("nodes", []),
            "stray": tree.get("stray", []),
        }
        return response, self._build_response(response_body)

    def osd_find(self, body='json', _id=None, timeout=None):
        response, body_data = self.osd(timeout=timeout)
        for osd in body_data.get("output", []):
            if osd.get("osd") == _id:
                crush_location = {}
                crush_location["host"] = osd.get("host", {}).get("name")
                response_body = {
                    **osd,
                    "crush_location": crush_location
                }
                return response, self._build_response(response_body)
        raise RookCephClientException(f"OSD with id {_id} not found")


class CephWrapper(object):

    _instance = None

    _lock = threading.Lock()

    def __new__(cls, endpoint=''):
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, endpoint=''):
        if not hasattr(self, '_initialized'):
            self._endpoint = endpoint
            self._backend = None
            self._backend_is_rook = self._is_rook()
            self._initialized = True

    def _get_backend(self):
        if self._backend is None:
            if self._backend_is_rook:
                self._backend = RookCephWrapper()
            else:
                self._backend = BareMetalCephWrapper(endpoint=self._endpoint)
        return self._backend

    def __getattr__(self, name):
        if name.startswith('_'):
            raise AttributeError(name)
        return getattr(self._get_backend(), name)

    def health(self, *args, **kwargs):
        return self._get_backend().health(*args, **kwargs)

    def fsid(self, *args, **kwargs):
        return self._get_backend().fsid(*args, **kwargs)

    def status(self, *args, **kwargs):
        return self._get_backend().status(*args, **kwargs)

    def df(self, *args, **kwargs):
        return self._get_backend().df(*args, **kwargs)

    def mon_dump(self, *args, **kwargs):
        return self._get_backend().mon_dump(*args, **kwargs)

    def osd_tree(self, *args, **kwargs):
        return self._get_backend().osd_tree(*args, **kwargs)

    def osd_find(self, *args, **kwargs):
        return self._get_backend().osd_find(*args, **kwargs)

    @staticmethod
    def _is_rook():
        try:
            try:
                config.load_incluster_config()
            except config.ConfigException:
                config.load_kube_config("/etc/kubernetes/admin.conf")

            custom_api = client.CustomObjectsApi()
            result = custom_api.list_namespaced_custom_object(
                group='ceph.rook.io',
                version='v1',
                namespace='rook-ceph',
                plural='cephclusters',
            )
            return bool(result.get('items'))
        except Exception:
            return False
