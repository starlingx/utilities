#
# Copyright (c) 2013-2018, 2025 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#

from collections import namedtuple
import os
import time

# noinspection PyUnresolvedReferences
from fm_api import constants as fm_constants
# noinspection PyUnresolvedReferences
from fm_api import fm_api
# noinspection PyUnresolvedReferences
from oslo_log import log as logging
from tsconfig import tsconfig
import yaml

from ceph_manager import constants
from ceph_manager import exception
# noinspection PyProtectedMember
from ceph_manager.i18n import _
from ceph_manager.i18n import _LE
from ceph_manager.i18n import _LI
from ceph_manager.i18n import _LW
from ceph_manager.usm_api import upgrade


LOG = logging.getLogger(__name__)


# This class is used to manage and filter Ceph alarms during upgrades
class HandleUpgradesMixin(object):

    def __init__(self, service, conf):
        self.service = service
        self.usm_api = upgrade.UsmApi(conf)
        self.patch_upgrade_in_progress = False
        self.release_upgrade_in_progress = False
        self.health_filters_for_upgrade = []
        self.health_filters_for_ignore = []

    def setup(self):
        self._load_config()
        self._refresh_upgrade_status()

    def _load_config(self):
        # Loads the Ceph manager configuration from a YAML file.
        # If the file doesn't exist, creates a default configuration.
        # Handles potential errors during file reading and parsing.
        try:
            with open(constants.CEPH_MANAGER_CONFIG_PATH, 'r') as file:
                data = yaml.safe_load(file)
        except FileNotFoundError:
            LOG.info(_LI("Ceph manager configuration file not found. Creating default."))
            default_config = {'health_filters_for_upgrade': [], 'health_filters_for_ignore': []}
            os.makedirs(os.path.dirname(constants.CEPH_MANAGER_CONFIG_PATH), exist_ok=True)
            try:
                with open(constants.CEPH_MANAGER_CONFIG_PATH, 'w') as file:
                    yaml.safe_dump(default_config, file)
                data = default_config
            except OSError as e:
                LOG.warning(_LW("Failed to create configuration: %s" % str(e)))

        except yaml.YAMLError as e:
            LOG.warning(_LW("Ceph manager configuration file parsing error: %s" % str(e)))
            return

        if data.get('health_filters_for_upgrade'):
            self.health_filters_for_upgrade = data['health_filters_for_upgrade']
            LOG.info(_LI("Health filters for upgrade loaded: %s" % self.health_filters_for_upgrade))

        if data.get('health_filters_for_ignore'):
            self.health_filters_for_ignore = data['health_filters_for_ignore']
            LOG.info(_LI("Health filters for upgrade loaded: %s" % self.health_filters_for_ignore))

    def _refresh_upgrade_status(self):
        try:
            upgrade = self.usm_api.retry_get_software_upgrade_status()
        except Exception as ex:
            LOG.warn(_LW(
                "Getting software upgrade status failed "
                "with: %s. Skip health filter attempt "
                "(will retry on next ceph status poll).") % str(ex))
            return

        state = upgrade.get('state')
        from_release = upgrade.get('from_release')
        to_release = upgrade.get('to_release')

        if (state and state != constants.UPGRADE_COMPLETED):
            if from_release == to_release:
                self.patch_upgrade_in_progress = True
                LOG.info(_LI("Patch upgrade in progress."))
            else:
                self.release_upgrade_in_progress = True
                LOG.info(_LI("Release upgrade in progress."))

    def filter_health_status(self, health):
        if health.get('checks'):
            if self.patch_upgrade_in_progress or self.release_upgrade_in_progress:
                for health_filter in self.health_filters_for_upgrade:
                    if health_filter in health['checks']:
                        LOG.info(_LI("Filtering Ceph health check '%s' during upgrade") % health_filter)
                        del health['checks'][health_filter]
            else:
                for health_filter in self.health_filters_for_ignore:
                    if health_filter in health['checks']:
                        LOG.info(_LI("Filtering Ceph health check '%s'") % health_filter)
                        del health['checks'][health_filter]

            # If there is no health detail, change the status to HEALTH_OK
            if not health['checks']:
                health['health'] = constants.CEPH_HEALTH_OK
        return health


class Monitor(HandleUpgradesMixin):

    def __init__(self, service, conf):
        self.service = service
        self.current_ceph_health = ""
        self.tiers_size = {}
        self.known_object_pool_name = None
        self.primary_tier_name = constants.SB_TIER_DEFAULT_NAMES[
            constants.SB_TIER_TYPE_CEPH] + constants.CEPH_CRUSH_TIER_SUFFIX
        super(Monitor, self).__init__(service, conf)

    def setup(self):
        super(Monitor, self).setup()

    def run(self):
        # Wait until Ceph cluster is up and we can get the fsid
        while True:
            try:
                self.ceph_get_fsid()
            except Exception:
                LOG.exception(
                    "Error getting fsid, will retry in %ss"
                    % constants.CEPH_HEALTH_CHECK_INTERVAL)
                time.sleep(constants.CEPH_HEALTH_CHECK_INTERVAL)
                continue
            else:
                break

        # Start monitoring ceph status
        while True:
            try:
                self.setup()
                self.ceph_poll_status()
            except Exception:
                LOG.exception(
                    "Error running periodic monitoring of ceph status, "
                    "will retry in %ss"
                    % constants.CEPH_HEALTH_CHECK_INTERVAL)
            time.sleep(constants.CEPH_HEALTH_CHECK_INTERVAL)

    def ceph_get_fsid(self):
        # Check whether an alarm has already been raised
        self._refresh_current_alarms()

        fsid = self._get_fsid()
        if fsid:
            # Clear alarm without entity_instance_id
            self._clear_fault(fm_constants.FM_ALARM_ID_STORAGE_CEPH, "")
            self.service.entity_instance_id = 'cluster=%s' % fsid
        else:
            health_info = {
                'health': constants.CEPH_HEALTH_DOWN,
                'checks': {},
                'mutes': []
            }
            # Raise alarm - it will not have an entity_instance_id
            self._report_fault(health_info, fm_constants.FM_ALARM_ID_STORAGE_CEPH)
            # Throws exception to get fsid again
            raise Exception("Could not get ceph fsid.")

    def ceph_poll_status(self):
        # get previous data every time in case:
        # * daemon restarted
        # * alarm was cleared manually but stored as raised in daemon
        self._refresh_current_alarms()

        health = self._get_health_detail()

        if health:
            health_info = self.filter_health_status(health)
            if health_info['health'] != constants.CEPH_HEALTH_OK:
                self._report_fault(health_info, fm_constants.FM_ALARM_ID_STORAGE_CEPH)
            else:
                self._clear_fault(fm_constants.FM_ALARM_ID_STORAGE_CEPH)
                # Clear alarm without entity_instance_id
                self._clear_fault(fm_constants.FM_ALARM_ID_STORAGE_CEPH, "")

        # Report OSD down/out even if ceph health is OK
        self._report_alarm_osds_health()

    def filter_health_status(self, health):
        return super(Monitor, self).filter_health_status(health)

    # CEPH HELPERS

    def _get_fsid(self):
        response = namedtuple('Response', ['ok', 'reason'])

        try:
            response, fsid = self.service.ceph_api.fsid(
                body='text', timeout=30)
        except Exception as e:
            response.ok = False
            response.reason = str(e)
            LOG.error(_LE("ceph_api.fsid error: %s" % response.reason))

        if response.ok:
            return fsid.strip()
        else:
            LOG.warning(_LW("Get fsid failed: %s") % response.reason)
            return None

    def _get_health_detail(self):
        response = namedtuple('Response', ['ok', 'reason'])

        try:
            response, body = self.service.ceph_api.health(
                body='json', detail='detail', timeout=30)
        except Exception as e:
            response.reason = str(e)

            LOG.error(_LE("ceph_api.health error: %s" % response.reason))

            health_info = {
                'health': constants.CEPH_HEALTH_DOWN,
                'checks': {},
                'mutes': []
            }

            return health_info

        if response.ok:
            health_info = body.get("output", {})
            return {
                'health': health_info.get('status', ''),
                'checks': health_info.get('checks', {}),
                'mutes': health_info.get('mutes', [])
            }

    # we have two root nodes 'cache-tier' and 'storage-tier'
    # to calculate the space that is used by the pools, we must only
    # use 'storage-tier'
    # this function determines if a certain node is under a certain
    # tree
    def host_is_in_root(self, search_tree, node, root_name):
        if node['type'] == 'root':
            if node['name'] == root_name:
                return True
            else:
                return False
        return self.host_is_in_root(search_tree,
                                    search_tree[node['parent']],
                                    root_name)

    # ALARM HELPERS

    @staticmethod
    def _check_storage_group(osd_tree, group_id,
                             hosts, osds, fn_report_alarm):
        reasons = set()
        degraded_hosts = set()
        severity = fm_constants.FM_ALARM_SEVERITY_CRITICAL

        for host_id in hosts:
            if len(osds[host_id]) == 0:
                reasons.add(constants.ALARM_REASON_NO_OSD)
                degraded_hosts.add(host_id)
            else:
                for osd_id in osds[host_id]:
                    if osd_tree[osd_id]['status'] == 'up':
                        if osd_tree[osd_id]['reweight'] == 0.0:
                            reasons.add(constants.ALARM_REASON_OSDS_OUT)
                            degraded_hosts.add(host_id)
                        else:
                            severity = fm_constants.FM_ALARM_SEVERITY_MAJOR
                    elif osd_tree[osd_id]['status'] == 'down':
                        reasons.add(constants.ALARM_REASON_OSDS_DOWN)
                        degraded_hosts.add(host_id)

        if constants.ALARM_REASON_OSDS_OUT in reasons \
           and constants.ALARM_REASON_OSDS_DOWN in reasons:
            reasons.add(constants.ALARM_REASON_OSDS_DOWN_OUT)
            reasons.remove(constants.ALARM_REASON_OSDS_OUT)

        if constants.ALARM_REASON_OSDS_DOWN in reasons \
           and constants.ALARM_REASON_OSDS_DOWN_OUT in reasons:
            reasons.remove(constants.ALARM_REASON_OSDS_DOWN)

        reason = "/".join(list(reasons))
        if severity == fm_constants.FM_ALARM_SEVERITY_CRITICAL:
            reason = "{} {}: {}".format(
                fm_constants.ALARM_CRITICAL_REPLICATION,
                osd_tree[group_id]['name'],
                reason)
        elif severity == fm_constants.FM_ALARM_SEVERITY_MAJOR:
            reason = "{} {}: {}".format(
                fm_constants.ALARM_MAJOR_REPLICATION,
                osd_tree[group_id]['name'],
                reason)

        if len(degraded_hosts) == 0:
            if (len(hosts) < 2 and
                    tsconfig.system_mode != constants.SYSTEM_MODE_SIMPLEX):
                fn_report_alarm(
                    osd_tree[group_id]['name'],
                    "{} {}: {}".format(
                        fm_constants.ALARM_MAJOR_REPLICATION,
                        osd_tree[group_id]['name'],
                        constants.ALARM_REASON_PEER_HOST_DOWN),
                    fm_constants.FM_ALARM_SEVERITY_MAJOR)
        elif len(degraded_hosts) == 1:
            fn_report_alarm(
                "{}.host={}".format(
                    osd_tree[group_id]['name'],
                    osd_tree[list(degraded_hosts)[0]]['name']),
                reason, severity)
        else:
            fn_report_alarm(
                osd_tree[group_id]['name'],
                reason, severity)

    def _check_storage_tier(self, osd_tree, tier_name, fn_report_alarm):
        for tier_id in osd_tree:
            if osd_tree[tier_id]['type'] != 'root':
                continue
            if osd_tree[tier_id]['name'] != tier_name:
                continue
            for group_id in osd_tree[tier_id]['children']:
                if osd_tree[group_id]['type'] != 'chassis':
                    continue
                if not osd_tree[group_id]['name'].startswith('group-'):
                    continue
                hosts = []
                osds = {}
                for host_id in osd_tree[group_id]['children']:
                    if osd_tree[host_id]['type'] != 'host':
                        continue
                    hosts.append(host_id)
                    osds[host_id] = []
                    for osd_id in osd_tree[host_id]['children']:
                        if osd_tree[osd_id]['type'] == 'osd':
                            osds[host_id].append(osd_id)
                self._check_storage_group(osd_tree, group_id, hosts,
                                          osds, fn_report_alarm)
            break

    def _current_health_alarm_equals(self, reason, severity):
        if not self.current_health_alarm:
            return False
        if getattr(self.current_health_alarm, 'severity', None) != severity:
            return False
        if getattr(self.current_health_alarm, 'reason_text', None) != reason:
            return False
        return True

    def _report_alarm_osds_health(self):
        if (self.patch_upgrade_in_progress or self.release_upgrade_in_progress) or \
                constants.OSD_DOWN_FILTER in self.health_filters_for_ignore:
            self._clear_fault(fm_constants.FM_ALARM_ID_STORAGE_CEPH_MAJOR)
            self._clear_fault(fm_constants.FM_ALARM_ID_STORAGE_CEPH_CRITICAL)
            return

        response, osd_tree = self.service.ceph_api.osd_tree(body='json', timeout=30)
        if not response.ok:
            LOG.error(_LE("Failed to retrieve Ceph OSD tree: "
                          "status_code: %(status_code)s, reason: %(reason)s") %
                      {"status_code": response.status_code,
                       "reason": response.reason})
            return
        osd_tree = dict([(n['id'], n) for n in osd_tree['output']['nodes']])
        alarms = []

        self._check_storage_tier(osd_tree, "storage-tier",
                                 lambda *args: alarms.append(args))

        old_alarms = {}
        for alarm_id in [
                fm_constants.FM_ALARM_ID_STORAGE_CEPH_MAJOR,
                fm_constants.FM_ALARM_ID_STORAGE_CEPH_CRITICAL]:
            alarm_list = self.service.fm_api.get_faults_by_id(alarm_id)
            if not alarm_list:
                continue
            for alarm in alarm_list:
                if alarm.entity_instance_id not in old_alarms:
                    old_alarms[alarm.entity_instance_id] = []
                old_alarms[alarm.entity_instance_id].append(
                    (alarm.alarm_id, alarm.reason_text))

        for peer_group, reason, severity in alarms:
            if self._current_health_alarm_equals(reason, severity):
                continue
            alarm_critical_major = fm_constants.FM_ALARM_ID_STORAGE_CEPH_MAJOR
            if severity == fm_constants.FM_ALARM_SEVERITY_CRITICAL:
                alarm_critical_major = (
                    fm_constants.FM_ALARM_ID_STORAGE_CEPH_CRITICAL)
            entity_instance_id = (
                self.service.entity_instance_id + '.peergroup=' + peer_group)
            alarm_already_exists = False
            if entity_instance_id in old_alarms:
                for alarm_id, old_reason in old_alarms[entity_instance_id]:
                    if (reason == old_reason and
                            alarm_id == alarm_critical_major):
                        # if the alarm is exactly the same, we don't need
                        # to recreate it
                        old_alarms[entity_instance_id].remove(
                            (alarm_id, old_reason))
                        alarm_already_exists = True
                    elif (alarm_id == alarm_critical_major):
                        # if we change just the reason, then we just remove the
                        # alarm from the list so we don't remove it at the
                        # end of the function
                        old_alarms[entity_instance_id].remove(
                            (alarm_id, old_reason))

                if (len(old_alarms[entity_instance_id]) == 0):
                    del old_alarms[entity_instance_id]

                # in case the alarm is exactly the same, we skip the alarm set
                if alarm_already_exists is True:
                    continue
            major_repair_action = constants.REPAIR_ACTION_MAJOR_CRITICAL_ALARM
            fault = fm_api.Fault(
                alarm_id=alarm_critical_major,
                alarm_type=fm_constants.FM_ALARM_TYPE_4,
                alarm_state=fm_constants.FM_ALARM_STATE_SET,
                entity_type_id=fm_constants.FM_ENTITY_TYPE_CLUSTER,
                entity_instance_id=entity_instance_id,
                severity=severity,
                reason_text=reason,
                probable_cause=fm_constants.ALARM_PROBABLE_CAUSE_15,
                proposed_repair_action=major_repair_action,
                service_affecting=constants.SERVICE_AFFECTING['HEALTH_WARN'])
            alarm_uuid = self.service.fm_api.set_fault(fault)
            if alarm_uuid:
                LOG.info(_LI(
                    "Created storage alarm %(alarm_uuid)s - "
                    "severity: %(severity)s, reason: %(reason)s, "
                    "service_affecting: %(service_affecting)s") % {
                    "alarm_uuid": str(alarm_uuid),
                    "severity": str(severity),
                    "reason": reason,
                    "service_affecting": str(
                        constants.SERVICE_AFFECTING['HEALTH_WARN'])})
            else:
                LOG.error(_LE(
                    "Failed to create storage alarm - "
                    "severity: %(severity)s, reason: %(reason)s, "
                    "service_affecting: %(service_affecting)s") % {
                    "severity": str(severity),
                    "reason": reason,
                    "service_affecting": str(
                        constants.SERVICE_AFFECTING['HEALTH_WARN'])})

        for entity_instance_id in old_alarms:
            for alarm_id, old_reason in old_alarms[entity_instance_id]:
                self.service.fm_api.clear_fault(alarm_id, entity_instance_id)

    @staticmethod
    def _parse_reason(health):
        """Parse reason strings received from Ceph"""
        if health['health'] in constants.CEPH_STATUS_CUSTOM:
            # Don't parse reason messages that we added
            return "Storage Alarm Condition: %(health)s. Ceph cluster is down." % health

        parsed_reasons_text = ""

        # Check if PGs have issues - we can't safely store the entire message
        # as it tends to be long
        for reason in health['checks'].values():
            summary = reason.get("summary", {})
            details = reason.get("detail", [])

            pgs_in_summary = summary and "pgs" in summary.get("message", "")
            pgs_in_details = any(["pgs" in detail.get('message', '') for detail in details])

            recovery_in_summary = summary and "recovery" in summary.get("message", "")
            recovery_in_details = any(["recovery" in detail.get('message', '') for detail in details])

            if pgs_in_summary or pgs_in_details:
                parsed_reasons_text += "PGs are degraded/stuck or undersized"
                break
            elif recovery_in_summary or recovery_in_details:
                parsed_reasons_text += "PGs are recovering or rebalancing"
                break

        # We need to keep the most important parts of the messages when storing
        # them to fm alarms, therefore text between [] brackets is truncated if
        # max size is reached.

        # Add brackets, if needed
        if len(parsed_reasons_text):
            lbracket = " ["
            rbracket = "]"
        else:
            lbracket = ""
            rbracket = ""

        msg = {"head": "Storage Alarm Condition: ",
               "tail": ". Please check 'ceph -s' for more details."}
        max_size = constants.FM_ALARM_REASON_MAX_SIZE - \
            len(msg["head"]) - len(msg["tail"])

        return (
            msg['head'] +
            (health['health'] + lbracket
             + parsed_reasons_text)[:max_size - 1] +
            rbracket + msg['tail'])

    def _report_fault(self, health, alarm_id):
        if alarm_id == fm_constants.FM_ALARM_ID_STORAGE_CEPH:
            new_severity = constants.SEVERITY[health['health']]
            new_reason_text = self._parse_reason(health)
            new_service_affecting = \
                constants.SERVICE_AFFECTING[health['health']]

            # Raise or update alarm if necessary
            if ((not self.current_health_alarm) or
                (self.current_health_alarm.__dict__['severity'] !=
                 new_severity) or
                (self.current_health_alarm.__dict__['reason_text'] !=
                 new_reason_text) or
                (self.current_health_alarm.__dict__['service_affecting'] !=
                 str(new_service_affecting))):

                fault = fm_api.Fault(
                    alarm_id=fm_constants.FM_ALARM_ID_STORAGE_CEPH,
                    alarm_type=fm_constants.FM_ALARM_TYPE_4,
                    alarm_state=fm_constants.FM_ALARM_STATE_SET,
                    entity_type_id=fm_constants.FM_ENTITY_TYPE_CLUSTER,
                    entity_instance_id=self.service.entity_instance_id,
                    severity=new_severity,
                    reason_text=new_reason_text,
                    probable_cause=fm_constants.ALARM_PROBABLE_CAUSE_15,
                    proposed_repair_action=constants.REPAIR_ACTION,
                    service_affecting=new_service_affecting)

                alarm_uuid = self.service.fm_api.set_fault(fault)
                if alarm_uuid:
                    LOG.info(_LI(
                        "Created storage alarm %(alarm_uuid)s - "
                        "severity: %(severity)s, reason: %(reason)s, "
                        "service_affecting: %(service_affecting)s") % {
                        "alarm_uuid": alarm_uuid,
                        "severity": new_severity,
                        "reason": new_reason_text,
                        "service_affecting": new_service_affecting})
                else:
                    LOG.error(_LE(
                        "Failed to create storage alarm - "
                        "severity: %(severity)s, reason: %(reason)s "
                        "service_affecting: %(service_affecting)s") % {
                        "severity": new_severity,
                        "reason": new_reason_text,
                        "service_affecting": new_service_affecting})

            # Log detailed reason for later analysis
            if (self.current_ceph_health != health['health'] or
                    self.detailed_health_reason != health['checks']):
                LOG.info(_LI("Ceph status changed: %(health)s "
                             "detailed reason: %(checks)s") % health)
                self.current_ceph_health = health['health']
                self.detailed_health_reason = health['checks']

    def _clear_fault(self, alarm_id, entity_instance_id=None):
        if entity_instance_id is None:
            entity_instance_id = self.service.entity_instance_id

        # Only clear the alarm if it exists
        if self._get_fault(alarm_id, entity_instance_id):
            LOG.info(_LI("Clearing health alarm"))

            self.service.fm_api.clear_fault(
                alarm_id,
                entity_instance_id)

    def _get_fault(self, alarm_id, entity_instance_id):
        return self.service.fm_api.get_fault(alarm_id, entity_instance_id)

    def clear_critical_alarm(self, group_name):
        alarm_list = self.service.fm_api.get_faults_by_id(
            fm_constants.FM_ALARM_ID_STORAGE_CEPH_CRITICAL)
        if alarm_list:
            for alarm in range(len(alarm_list)):
                group_id = alarm_list[alarm].entity_instance_id.find("group-")
                group_instance_name = (
                    "group-" +
                    alarm_list[alarm].entity_instance_id[group_id + 6])
                if group_name == group_instance_name:
                    self.service.fm_api.clear_fault(
                        fm_constants.FM_ALARM_ID_STORAGE_CEPH_CRITICAL,
                        alarm_list[alarm].entity_instance_id)

    def _refresh_current_alarms(self):
        """Retrieve currently raised alarm"""
        self.current_health_alarm = self._get_fault(fm_constants.FM_ALARM_ID_STORAGE_CEPH,
                                                    self.service.entity_instance_id)
        if self.current_health_alarm:
            LOG.info(_LI("Current alarm: %s") %
                     str(self.current_health_alarm.__dict__))
