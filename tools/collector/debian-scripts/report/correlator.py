########################################################################
#
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# This file contains the Correlator class.
# The Correlator class contains algorithms that search for failures.
#
# The Correlator class reads through all the output files created by
# the plugins and determines failures and their root causes, as well as
# finds significant events, alarms transitions, and state changes.
# A summary of the findings are printed to standard output and output
# files are created in the report directory.
#
# TODO: Modularize code and separate methods into their own files
#
########################################################################

from datetime import datetime
from datetime import timedelta
import logging
import os
import re

logger = logging.getLogger(__name__)


class Correlator:
    def __init__(self, plugin_output_dir):
        """Constructor for the Correlator class

        Parameters:
            plugin_output_dir (string): Path to directory with output files
                                        from plugins
        """
        self.plugin_output_dir = plugin_output_dir

    def run(self, hostname):
        """Searches through the output files created by the plugins for
        failures and determines their causes, as well as extracts significant
        events and state changes

        Errors:
            FileNotFoundError
        """
        failures = []
        try:
            failures += self.uncontrolled_swact()
        except FileNotFoundError as e:
            logger.error(e)

        try:
            failures += self.mtc_errors()
        except FileNotFoundError as e:
            logger.error(e)

        events = []
        try:
            events += self.get_events(hostname)
        except FileNotFoundError as e:
            logger.error(e)

        alarms = []
        try:
            alarms += self.get_alarms(hostname)
        except FileNotFoundError as e:
            logger.error(e)

        state_changes = []
        try:
            state_changes += self.get_state_changes(hostname)
        except FileNotFoundError as e:
            logger.error(e)

        return (sorted(failures), sorted(events), sorted(alarms),
                sorted(state_changes))

    def uncontrolled_swact(self):
        """Searches through the output file created by the swact activity
        plugin for uncontrolled swacts and determines their causes through
        other indicators, like the log "Neighbour [..] is now in the down"

        Errors:
            FileNotFoundError
        """
        data = []

        # Variables to keep track of indicators for failure causes
        start_time = end_time = svc_failed = None
        ctrlr_down = None  # Active controller that went down, causing swact
        ctrlr_svc_fail = None  # Active controller where service failed
        ctrlr_link_down = None  # Orig. active controller when link went down
        hb_loss = active_failed = go_active_failed = link_down = False

        # Open output file from swact activity plugin and read it
        file_path = os.path.join(self.plugin_output_dir, "swact_activity")

        with open(file_path, "r") as swact_activity:
            for line in swact_activity:
                if "Uncontrolled swact" in line and not start_time:
                    start_time = datetime.strptime(line[0:19],
                                                   "%Y-%m-%dT%H:%M:%S")
                    if ("Host from active to failed, Peer from standby to "
                            "active" in line):
                        link_down = True
                        ctrlr_link_down = re.findall(
                            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3} (.+) "
                            "sm:", line)[0]
                elif (re.search("Neighbor (.+) is now in the down", line)
                        and start_time and not ctrlr_down):
                    ctrlr_down = re.findall(
                        r"Neighbor \((.+)\) received event", line)[0]
                elif (re.search("Service (.+) is failed and has reached max "
                                "failures", line) and not svc_failed):
                    svc_failed = re.findall(
                        r"Service \((.+)\) is failed", line)[0]
                    ctrlr_svc_fail = re.findall(
                        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3} (.+) sm:",
                        line)[0]
                elif (svc_failed and re.search(
                        "active-failed\\s+\\| disabling-failed\\s+\\| "
                        + svc_failed, line)):
                    if re.search(r"\| go-active-failed\s+\|", line):
                        go_active_failed = True
                    else:
                        active_failed = True
                elif "Swact update" in line and start_time and not end_time:
                    end_time = datetime.strptime(line[0:19],
                                                 "%Y-%m-%dT%H:%M:%S")
                    if ctrlr_down:
                        try:
                            hb_loss = self.search_hb_loss(
                                start_time, end_time, ctrlr_down)
                        except FileNotFoundError as e:
                            logger.error(e)

                    start_time = start_time.strftime("%Y-%m-%dT%H:%M:%S")
                    end_time = end_time.strftime("%Y-%m-%dT%H:%M:%S")
                    if link_down:
                        data.append(start_time + " to " + end_time
                                    + " Uncontrolled swact, refer to SM logs "
                                    "for in-depth analysis, original active "
                                    "controller: " + ctrlr_link_down + "\n")
                    elif ctrlr_down:
                        if hb_loss:
                            data.append(start_time + " to " + end_time
                                        + " Uncontrolled swact due to "
                                        "spontaneous reset of active "
                                        "controller " + ctrlr_down + "\n")
                        else:
                            data.append(start_time + " to " + end_time
                                        + " Uncontrolled swact likely due to "
                                        "spontaneous reset of active "
                                        "controller " + ctrlr_down + "\n")
                    elif svc_failed:
                        if active_failed and go_active_failed:
                            data.append(start_time + " to " + end_time
                                        + " Uncontrolled swact due to service "
                                        "failure (" + svc_failed + ") twice "
                                        "in 2 minutes was unsuccessful so "
                                        "\"bounced back\" to original active "
                                        "controller " + ctrlr_svc_fail + "\n")
                        elif active_failed:
                            data.append(start_time + " to " + end_time
                                        + " Uncontrolled swact due to service "
                                        "failure (" + svc_failed + ") twice "
                                        "in 2 minutes on active controller "
                                        + ctrlr_svc_fail + "\n")
                        else:
                            data.append(start_time + " to " + end_time
                                        + " Uncontrolled swact likely due to "
                                        "service failure (" + svc_failed
                                        + ") twice in 2 minutes on active "
                                        "controller " + ctrlr_svc_fail + "\n")

                    start_time = end_time = svc_failed = None
                    ctrlr_down = ctrlr_svc_fail = ctrlr_link_down = None
                    hb_loss = active_failed = go_active_failed = False
                    link_down = False

        return data

    def mtc_errors(self):
        """Searches through the output file created by the maintenance errors
        plugin for failures and determines their causes through other
        indicators, like the log "Loss Of Communication for 5 seconds"

        Errors:
            FileNotFoundError
        """
        data = []

        # Variables to keep track of indicators for failure causes
        goenable_start = goenable_end = goenable_host = None
        goenable_tst_f = config_tst_f = None  # Tests failed
        config_start = config_end = config_host = puppet_error = None
        hb_loss_start = hb_loss_end = hb_loss_host = None
        daemon_fail = comm_loss = auto_recov_dis = False

        # Open output file from maintenance errors plugin and read it
        file_path = os.path.join(self.plugin_output_dir, "maintenance_errors")

        with open(file_path, "r") as mtc:
            for line in mtc:
                if "auto recovery disabled" in line and not auto_recov_dis:
                    # Check if previous failure recorded was go-enable,
                    # configuration or heartbeat failure
                    if (data and
                        re.search(r"Go-enable|[cC]onfiguration|Heartbeat",
                                  data[-1])):
                        host = re.findall(r"failure on ([^\s]+)", data[-1])
                        # Check if host in auto recovery disabled mode is same
                        # as host with previous failure
                        if (host and re.search(
                                host[0] + " auto recovery disabled", line)):
                            old = data[-1].split("due", 1)
                            if len(old) == 1:
                                data[-1] = (data[-1][:-1]
                                            + " (auto recovery disabled)\n")
                            else:
                                data[-1] = (old[0]
                                            + "(auto recovery disabled) due"
                                            + old[1])
                            auto_recov_dis = True
                elif "GOENABLED Failed" in line and not goenable_start:
                    goenable_start, auto_recov_dis = line[0:19], False
                    goenable_host = re.findall(
                        "Error : (.+) got GOENABLED Failed", line)[0]
                elif ("configuration failed or incomplete" in line
                        and not config_start):
                    config_start = datetime.strptime(line[0:19],
                                                     "%Y-%m-%dT%H:%M:%S")
                    auto_recov_dis = False
                    config_host = re.findall(
                        "Error : (.+) configuration failed", line)[0]
                elif "Heartbeat Loss" in line:
                    # Check if previous failure recorded was heartbeat loss
                    # due to missing heartbeat messages
                    if ("(during recovery soak)" in line and data and
                            re.search("missing heartbeat messages", data[-1])):
                        host = re.findall(
                            "failure on (.+) due to", data[-1])[0]
                        # Check if host with hearbeat loss failure is the same
                        # as host with previous failure
                        if (re.search(host + " (.+) Heartbeat Loss (.+) "
                                      "\\(during recovery soak\\)", line)):
                            old = data[-1]
                            data[-1] = (old[0:23] + line[0:19] + old[42:-1]
                                        + " (recovery over disabled due to "
                                        "heartbeat soak failure)\n")
                    else:
                        hb_loss_start = line[0:19]
                        comm_loss = auto_recov_dis = False
                        hb_loss_host = re.findall("Error : (.+) [CM]", line)[0]
                # Check if previous failure recorded was heartbeat loss due to
                # missing heartbeat messages
                elif ("regained MTCALIVE from host that has rebooted" in line
                        and data and re.search(r"Heartbeat loss failure (.+) "
                                               r"\(recovery over disabled\)",
                                               data[-1])):
                    host = re.findall("failure on (.+) due to", data[-1])[0]
                    if re.search(host + " regained MTCALIVE", line):
                        old = data[-1].split("due", 1)[0]
                        data[-1] = (old[0:23] + line[0:19] + old[42:]
                                    + "due to uncontrolled reboot\n")
                elif (hb_loss_start and not comm_loss and hb_loss_host and
                      re.search(hb_loss_host + " Loss Of Communication for 5 "
                                "seconds", line)):
                    comm_loss = True
                elif re.search("mtcClient --- (.+)Error : FAILED:", line):
                    if goenable_start and not goenable_tst_f:
                        goenable_tst_f = re.findall(
                            r"Error : FAILED: (.+) \(\d", line)[0]
                    elif config_start and not config_tst_f:
                        config_tst_f = re.findall(
                            r"Error : FAILED: (.+) \(\d", line)[0]
                elif (goenable_host and not goenable_end and
                      re.search(goenable_host + " Task: In-Test Failure, "
                                "threshold reached", line)):
                    goenable_end = line[0:19]
                    if goenable_tst_f:
                        data.append(goenable_start + " to " + goenable_end
                                    + " Go-enable test failure on "
                                    + goenable_host + " due to failing of "
                                    + goenable_tst_f + "\n")
                    else:
                        data.append(goenable_start + " to " + goenable_end
                                    + " Go-enable test failure on "
                                    + goenable_host + " due to unknown test "
                                    "failing\n")

                    goenable_start = goenable_end = goenable_host = None
                    goenable_tst_f = None
                elif (config_host and not config_end and
                      re.search(config_host + " Task: Configuration failure, "
                                "threshold reached", line)):
                    config_end = datetime.strptime(line[0:19],
                                                   "%Y-%m-%dT%H:%M:%S")
                    if (config_tst_f
                            != "/etc/goenabled.d/config_goenabled_check.sh"):
                        try:
                            daemon_fail = self.search_daemon_fail(
                                config_start, config_end, config_host)
                        except FileNotFoundError as e:
                            logger.error(e)

                    if (config_tst_f ==
                        "/etc/goenabled.d/config_goenabled_check.sh"
                            or daemon_fail):
                        try:
                            puppet_error = self.search_puppet_error(
                                config_start, config_end)
                        except FileNotFoundError as e:
                            logger.error(e)

                        config_start = config_start.strftime(
                            "%Y-%m-%dT%H:%M:%S")
                        config_end = config_end.strftime("%Y-%m-%dT%H:%M:%S")
                        if puppet_error:
                            data.append(config_start + " to " + config_end
                                        + " Configuration failure on "
                                        + config_host + " due to:\n"
                                        + puppet_error)
                        else:
                            data.append(config_start + " to " + config_end
                                        + " Configuration failure on "
                                        + config_host
                                        + " due to unknown cause\n")
                    else:
                        config_start = config_start.strftime(
                            "%Y-%m-%dT%H:%M:%S")
                        config_end = config_end.strftime("%Y-%m-%dT%H:%M:%S")
                        data.append(config_start + " to " + config_end
                                    + " Possible configuration failure on "
                                    + config_host + "\n")

                    config_start = config_end = config_host = None
                    config_tst_f = puppet_error = None
                    daemon_fail = False
                elif (hb_loss_start and not hb_loss_end and hb_loss_host and
                      re.search(hb_loss_host + " Connectivity Recovered ",
                                line)):
                    hb_loss_end = line[0:19]
                    data.append(hb_loss_start + " to " + hb_loss_end
                                + " Heartbeat loss failure on " + hb_loss_host
                                + " due to too many missing heartbeat "
                                "messages\n")

                    hb_loss_start = hb_loss_end = hb_loss_host = None
                    comm_loss = False
                elif (hb_loss_start and comm_loss and not hb_loss_end and
                      hb_loss_host and re.search(
                          hb_loss_host + " Graceful Recovery Wait", line)):
                    hb_loss_end = line[0:19]
                    data.append(hb_loss_start + " to " + hb_loss_end
                                + " Heartbeat loss failure on " + hb_loss_host
                                + " due to too many missing heartbeat "
                                "messages (recovery over disabled)\n")

                    hb_loss_start = hb_loss_end = hb_loss_host = None
                    comm_loss = False

        return data

    def search_hb_loss(self, start_time, end_time, host):
        """Searches through the output file created by the heartbeat loss
        plugin for "Heartbeat Loss" message from host between one minute before
        start_time and end_time

        Errors:
            FileNotFoundError
        """
        hb_loss = False

        # Open output file from heartbeat loss plugin and read it
        file_path = os.path.join(self.plugin_output_dir, "heartbeat_loss")

        with open(file_path, "r") as heartbeat_loss:
            for line in heartbeat_loss:
                if (re.search("Error : " + host + " (.+) Heartbeat Loss ",
                              line)):
                    date = datetime.strptime(line[0:19], "%Y-%m-%dT%H:%M:%S")
                    if (date >= start_time - timedelta(minutes=1)
                            and date <= end_time):
                        hb_loss = True
                        break

        return hb_loss

    def search_daemon_fail(self, start_time, end_time, host):
        """Searches through the output file created by the daemon failures
        plugin for "Failed to run the puppet manifest" message from host
        between 10 seconds before start_time and end_time

        Errors:
            FileNotFoundError
        """
        daemon_fail = False

        # Open output file from daemon failures plugin and read it
        file_path = os.path.join(self.plugin_output_dir, "daemon_failures")

        with open(file_path, "r") as daemon_failures:
            for line in daemon_failures:
                if (re.search("\\d " + host
                              + " (.+) Failed to run the puppet manifest",
                              line)):
                    date = datetime.strptime(line[0:19], "%Y-%m-%dT%H:%M:%S")
                    if (date >= start_time - timedelta(seconds=10)
                            and date <= end_time):
                        daemon_fail = True
                        break

        return daemon_fail

    def search_puppet_error(self, start_time, end_time):
        """Searches through the output file created by the puppet errors
        plugin for "Error:" message between 10 seconds before start_time and
        end_time and returns it

        Errors:
            FileNotFoundError
        """
        puppet_log = None

        # Open output file from puppet errors plugin and read it
        file_path = os.path.join(self.plugin_output_dir, "puppet_errors")

        with open(file_path, "r") as puppet_errors:
            for line in puppet_errors:
                if "Error: " in line:
                    date = datetime.strptime(line[0:19], "%Y-%m-%dT%H:%M:%S")
                    if (date >= start_time - timedelta(seconds=10)
                            and date <= end_time):
                        puppet_log = line
                        break

        return puppet_log

    def get_events(self, hostname):
        """Searches through the output files created by the plugins for
        significant events and summarizes them, such as "force failed by SM"

        Errors:
            FileNotFoundError
        """
        data = []

        # Variables to keep track of details for events
        mnfa_start, mnfa_hist = None, ""

        # Open output file from maintenance errors plugin and read it
        file_path = os.path.join(self.plugin_output_dir, "maintenance_errors")

        with open(file_path, "r") as mtc:
            for line in mtc:
                if "force failed by SM" in line:
                    host = re.findall("Error : (.+) is being", line)[0]
                    if hostname == "all" or host == hostname:
                        data.append(line[0:19] + " " + host
                                    + " force failed by SM\n")
                elif "Graceful Recovery Failed" in line:
                    host = re.findall("Info : (.+) Task:", line)[0]
                    if hostname == "all" or host == hostname:
                        data.append(line[0:19] + " " + host
                                    + " graceful recovery failed\n")
                elif "MNFA ENTER" in line:
                    mnfa_start = datetime.strptime(line[0:19],
                                                   "%Y-%m-%dT%H:%M:%S")
                elif "MNFA POOL" in line:
                    pool_hosts = len(line.split("MNFA POOL: ")[1].split())
                    if mnfa_start:
                        mnfa_hist += (" " + str(pool_hosts))
                    else:
                        data_len = len(data)
                        for n in range(0, data_len):
                            event = data[data_len - 1 - n]
                            if "Multi-node failure" in event:
                                temp = " " + str(pool_hosts) + ")\n"
                                data[data_len - 1 - n] = event[:-2] + temp
                                break
                elif "MNFA EXIT" in line:
                    mnfa_duration = datetime.strptime(line[0:19],
                                                      "%Y-%m-%dT%H:%M:%S")
                    mnfa_duration -= mnfa_start
                    mnfa_start = mnfa_start.strftime("%Y-%m-%dT%H:%M:%S")
                    data.append(mnfa_start + " Multi-node failure avoidance "
                                + "(duration: " + str(mnfa_duration)
                                + "; history:" + mnfa_hist + ")\n")

                    mnfa_start, mnfa_hist = None, ""

        # Open output file from swact activity plugin and read it
        file_path = os.path.join(self.plugin_output_dir, "swact_activity")

        with open(file_path, "r") as swact_activity:
            for line in swact_activity:
                if (re.search("Service (.+) is failed and has reached max "
                              "failures", line)):
                    host = re.findall(
                        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3} (.+) sm:",
                        line)[0]
                    svc_failed = re.findall(
                        r"Service \((.+)\) is failed", line)[0]
                    if hostname == "all" or host == hostname:
                        data.append(line[0:19] + " " + host
                                    + " service failure (" + svc_failed
                                    + ")\n")

        return data

    def get_alarms(self, hostname):
        """Searches through the 'alarm' output file created by the alarm plugin
        and summarizes which alarms were found as well as the number of times
        they were set and cleared

        Errors:
            FileNotFoundError
        """
        data = []

        # Open 'alarm' output file from alarm plugin and read it
        file_path = os.path.join(self.plugin_output_dir, "alarm")

        with open(file_path, "r") as alarm:
            extract = False
            for line in alarm:
                if re.search("   \\d", line) and extract:
                    if line.split()[2] == "set":
                        data[-1]["set"] += 1
                    else:
                        data[-1]["clear"] += 1
                elif hostname == "all" or hostname in line:
                    extract = True
                    alarm = {
                        "name": line[:-1],
                        "set": 0,
                        "clear": 0,
                    }

                    data.append(alarm)
                else:
                    extract = False

        temp = []
        for entry in data:
            temp.append(entry["name"] + " - set: " + str(entry["set"])
                        + ", clear: " + str(entry["clear"]) + "\n")
        data = temp

        return data

    def get_state_changes(self, hostname):
        """Searches through the output files created by the state changes
        plugin and summarizes the changes of state of the hosts, such as
        "is ENABLED"

        Errors:
            FileNotFoundError
        """
        data = []

        # Open output file from state changes plugin and read it
        file_path = os.path.join(self.plugin_output_dir, "state_changes")

        with open(file_path, "r") as state_changes:
            for line in state_changes:
                if "is ENABLED" in line:
                    host = re.findall("Info : (.+) is ENABLED", line)[0]
                    state = re.findall("is (.+)\n", line)[0].lower()
                    if hostname == "all" or hostname in host:
                        data.append(line[0:19] + " " + host + " " + state
                                    + "\n")
                elif "locked-disabled" in line:
                    host = re.findall(
                        "Info : (.+) u?n?locked-disabled", line)[0]
                    if hostname == "all" or host == hostname:
                        data.append(line[0:19] + " " + host + " disabled\n")

        return data
