########################################################################
#
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# This file contains the ExecutionEngine class.
# The ExecutionEngine class contains all the available algorithms.
#
# The ExecutionEngine class runs plugins and gathers relevant logs and
# information, creating output files in the report directory.
#
# TODO: Modularize code and separate plugin algorithms into their own
#       files
#
########################################################################

from datetime import datetime
import gzip
import logging
import os
import re
import shutil
import subprocess
import tarfile

import algorithms
from correlator import Correlator


logger = logging.getLogger(__name__)


class ExecutionEngine:
    def __init__(self, opts, output_directory):
        """Constructor for the ExecutionEngine class

        Parameters:
            opts (dictionary): Options from command line
        """
        self.opts = opts
        self.hosts = {"controllers": {}, "workers": {}, "storages": {}}
        self.active_controller_directory = None

        # Uncompresses host tar files if not already done
        with open(os.path.join(output_directory, "untar.log"), "a") as logfile:
            for obj in (os.scandir(self.opts.directory)):
                info = os.path.splitext(obj.name)
                if (obj.is_file() and obj.name != "report_tool.tgz" and
                        tarfile.is_tarfile(obj.path) and not
                        os.path.isdir(os.path.join(self.opts.directory,
                                                   info[0]))):
                    try:
                        subprocess.run(["tar", "xzfC", obj.path,
                                        self.opts.directory],
                                       stderr=logfile, check=True)
                        subprocess.run(["echo", "uncompressed", obj.name],
                                       check=True)
                    except subprocess.CalledProcessError as e:
                        logger.error(e)

        for folder in (f.path for f in os.scandir(self.opts.directory)):
            database_path = os.path.join(folder, "var", "extra", "database")
            host_info_path = os.path.join(folder, "var", "extra", "host.info")

            if os.path.isdir(database_path) and os.listdir(database_path):
                self.active_controller_directory = folder

            if os.path.exists(host_info_path):
                hostname, subfunction = self._extract_subfunction(
                    host_info_path)
                if "controller" in subfunction:
                    self.hosts["controllers"][hostname] = folder
                elif "worker" in subfunction:
                    self.hosts["workers"][hostname] = folder
                elif "storage" in subfunction:
                    self.hosts["storages"][hostname] = folder

        if not self.active_controller_directory:
            raise ValueError("Active controller not found")

    def execute(self, plugins, output_directory):
        """Run a list of plugins

        Parameters:
            plugins (Plugin list): List of plugins to run

        Errors:
            FileNotFoundError
        """
        plugin_output_dir = os.path.join(output_directory, "plugins")
        os.makedirs(plugin_output_dir, exist_ok=True)

        for plugin in plugins:
            processing = "Processing plugin: " + os.path.basename(plugin.file)
            hosts = {}
            if (
                plugin.state["hosts"] and len(plugin.state["hosts"]) >= 1
            ):  # if host list is given
                logger.info(
                    f"Processing plugin: {os.path.basename(plugin.file)}")

                for h in plugin.state["hosts"]:
                    if h == "all":
                        hosts.update(self.hosts["workers"])
                        hosts.update(self.hosts["storages"])
                        hosts.update(self.hosts["controllers"])
                    else:
                        hosts.update(self.hosts[h])

                for hostname, folderpath in hosts.items():

                    events = []
                    if plugin.state["algorithm"] == algorithms.SUBSTRING:
                        events = self.substring(
                            plugin.state["substring"],
                            [
                                os.path.join(folderpath, file)
                                for file in plugin.state["files"]
                            ],
                        )

                        # creating output file
                        output_file = os.path.join(
                            plugin_output_dir,
                            f"substring_{hostname}",
                        )
                        if self.opts.verbose:
                            logger.info("output at "
                                        + os.path.relpath(output_file))
                        with open(output_file, "w") as file:
                            file.write(
                                f"Date range: {self.opts.start} until "
                                f"{self.opts.end}\n"
                            )
                            file.write(
                                f"substrings: "
                                f"{' '.join(plugin.state['substring'])}\n"
                            )
                            for line in events:
                                if line[-1] == "\n":
                                    file.write(line)
                                else:
                                    file.write(line + "\n")
            else:
                if plugin.state["algorithm"] == algorithms.SYSTEM_INFO:
                    info = self.system_info()
                    system_info_output = os.path.join(plugin_output_dir,
                                                      "system_info")
                    with open(system_info_output, "w") as file:
                        for i in info:
                            file.write(i + "\n")

                        for k, v in self.hosts.items():
                            file.write(f"{k}: {','.join(v.keys())}\n")
                    if self.opts.verbose:
                        logger.info(processing + ", output at "
                                    + os.path.relpath(system_info_output))
                    else:
                        logger.info(processing)

                elif plugin.state["algorithm"] == algorithms.AUDIT:
                    hosts = {}
                    hosts.update(self.hosts["workers"])
                    hosts.update(self.hosts["storages"])
                    hosts.update(self.hosts["controllers"])

                    for hostname, folderpath in hosts.items():
                        self._create_output_file(
                            f"{hostname}_audit",
                            plugin_output_dir,
                            self.audit(
                                plugin.state["start"],
                                plugin.state["end"],
                                os.path.join(
                                    folderpath, "var", "log", "dcmanager",
                                    "audit.log"
                                ),
                            ),
                            processing,
                        )

                elif plugin.state["algorithm"] == algorithms.SWACT_ACTIVITY:
                    self._create_output_file(
                        "swact_activity", plugin_output_dir,
                        self.swact_activity(), processing
                    )

                elif plugin.state["algorithm"] == algorithms.PUPPET_ERRORS:
                    self._create_output_file(
                        "puppet_errors", plugin_output_dir,
                        self.puppet_errors(), processing
                    )

                elif plugin.state["algorithm"] == algorithms.PROCESS_FAILURES:
                    self._create_output_file(
                        "process_failures", plugin_output_dir,
                        self.process_failures(), processing
                    )

                elif plugin.state["algorithm"] == algorithms.ALARM:
                    alarms, logs = self.alarm(
                        plugin.state["alarm_exclude"],
                        plugin.state["entity_exclude"]
                    )
                    alarm_output = os.path.join(plugin_output_dir, "alarm")
                    log_output = os.path.join(plugin_output_dir, "log")

                    # creating output alarm file
                    with open(alarm_output, "w") as file:
                        for k, v in alarms.items():
                            file.write(f"{k}:\n")
                            for date in v["dates"]:
                                file.write(f"   {date}\n")

                    # creating output log file
                    with open(log_output, "w") as file:
                        for k, v in logs.items():
                            file.write(f"{k}: {v['count']}\n")
                        file.write("\n")
                        for k, v in logs.items():
                            file.write(f"{k}:\n")
                            for date in v["dates"]:
                                file.write(f"   {date}\n")
                    if self.opts.verbose:
                        logger.info(processing + ", output at "
                                    + os.path.relpath(alarm_output)
                                    + ", " + os.path.relpath(log_output))
                    else:
                        logger.info(processing)
                elif plugin.state["algorithm"] == algorithms.HEARTBEAT_LOSS:
                    self._create_output_file(
                        "heartbeat_loss", plugin_output_dir,
                        self.heartbeat_loss(), processing
                    )
                elif plugin.state["algorithm"] == algorithms.MAINTENANCE_ERR:
                    self._create_output_file(
                        "maintenance_errors", plugin_output_dir,
                        self.maintenance_errors(), processing
                    )
                elif plugin.state["algorithm"] == algorithms.DAEMON_FAILURES:
                    self._create_output_file(
                        "daemon_failures", plugin_output_dir,
                        self.daemon_failures(), processing
                    )
                elif plugin.state["algorithm"] == algorithms.STATE_CHANGES:
                    self._create_output_file(
                        "state_changes", plugin_output_dir,
                        self.state_changes(), processing
                    )

        if not self.opts.verbose:
            logger.info("Output files for plugins can be found at " +
                        os.path.relpath(plugin_output_dir))

        # Running the correlator and printing the output from it
        self.run_correlator(output_directory, plugin_output_dir)

    # Built-in algorithms ------------------------------
    def alarm(self, alarm_exclude=[], entity_exclude=[]):
        """Alarm algorithm
        Gathers list of alarms and customer logs

        Parameters:
            alarm_exclude (string list) : List of alarm id patterns to not
                                          search for
            entity_exclude (string list): List of entity id patterns to not
                                          search for
        """
        alarm_data = {}
        log_data = {}

        with open(
            os.path.join(
                self.active_controller_directory,
                "var", "extra", "database", "fm.db.sql.txt"
            )
        ) as file:
            start = False
            for line in file:
                # start of event log
                if re.search(r"COPY (public\.)?event_log", line):
                    start = True
                elif start and line == "\\.\n":
                    break
                elif start:
                    entry = re.split(r"\t", line)

                    INDEX_ALARM_ID = 5
                    INDEX_ACTION = 6
                    INDEX_ENTITY_ID = 8
                    INDEX_ALARM_DATE = 9
                    INDEX_SEVERITY = 10

                    alarm_id = entry[INDEX_ALARM_ID]
                    entity_id = entry[INDEX_ENTITY_ID]
                    action = entry[INDEX_ACTION]
                    severity = entry[INDEX_SEVERITY]
                    alarm_date = entry[INDEX_ALARM_DATE]

                    entry_date = alarm_date.replace(
                        " ", "T"
                    )  # making time format of alarm the same
                    if (self.opts.start <= entry_date
                            and entry_date <= self.opts.end):
                        cont = True
                        # Checks if the alarm is in the user specified list of
                        # alarm or entity ids
                        for id in alarm_exclude:
                            if id in alarm_id:
                                cont = False
                                break

                        for entity in entity_exclude:
                            if entity in entity_id:
                                cont = False
                                break

                        if not cont:
                            continue

                        try:
                            if action == "log":
                                log_info = log_data[
                                    f"{alarm_id} {entity_id} {severity}"
                                ]
                                log_info["count"] += 1
                                log_info["dates"].append(alarm_date)
                            else:
                                alarm_info = alarm_data[
                                    f"{alarm_id} {entity_id} {severity}"
                                ]
                                alarm_info["dates"].append(
                                    f"{alarm_date} {action}")
                        except KeyError:
                            if entry[6] != "log":
                                alarm_data[
                                    f"{alarm_id} {entity_id} {severity}"
                                ] = {
                                    "dates": [f"{alarm_date} {action}"],
                                }
                            else:
                                log_data[
                                    f"{alarm_id} {entity_id} {severity}"
                                ] = {
                                    "count": 1,
                                    "dates": [alarm_date],
                                }

        for _, v in alarm_data.items():
            v["dates"] = sorted(v["dates"])
            temp = []
            temp.append(v["dates"][0])
            for i in range(1, len(v["dates"])):
                if v["dates"][i].split()[2] != v["dates"][i-1].split()[2]:
                    temp.append(v["dates"][i])
            v["dates"] = temp

        for _, v in log_data.items():
            v["dates"] = sorted(v["dates"])

        return alarm_data, log_data

    def substring(self, substr, files):
        """Substring algorithm
        Looks for substrings within files

        Parameters:
            substr (string list): List of substrings to look for
            files  (string list): List of absolute filepaths to search in

        Errors:
            FileNotFoundError
        """
        # don't analyze older files, continue with current file
        CONTINUE_CURRENT = 0
        # analyze older files, continue with current file
        CONTINUE_CURRENT_OLD = 1

        data = []
        for file in files:
            try:
                if not os.path.exists(file):
                    if (re.search("controller-1_(.+)/var/log/mtcAgent.log",
                                  file)):
                        continue
                    raise FileNotFoundError(f"File not found: {file}")
                cont = True
                # Searching through file
                command = (f"""grep -Ea "{'|'.join(s for s in substr)}" """
                           f"""{file} 2>/dev/null""")
                status = self._continue(file)

                if (status == CONTINUE_CURRENT
                        or status == CONTINUE_CURRENT_OLD):
                    # continue with current file
                    if status == CONTINUE_CURRENT:
                        cont = False
                    self._evaluate_substring(data, command)

                # Searching through rotated log files that aren't compressed
                n = 1
                while os.path.exists(f"{file}.{n}") and cont:
                    command = (f"""grep -Ea "{'|'.join(s for s in substr)}" """
                               f"""{file}.{n} 2>/dev/null""")
                    status = self._continue(f"{file}.{n}")

                    if (status == CONTINUE_CURRENT
                            or status == CONTINUE_CURRENT_OLD):
                        if status == CONTINUE_CURRENT:
                            cont = False
                        self._evaluate_substring(data, command)

                    n += 1

                # Searching through rotated log files
                while os.path.exists(f"{file}.{n}.gz") and cont:
                    command = (f"""zgrep -E "{'|'.join(s for s in substr)}" """
                               f"""{file}.{n}.gz 2>/dev/null""")
                    status = self._continue(f"{file}.{n}.gz", compressed=True)

                    if (status == CONTINUE_CURRENT
                            or status == CONTINUE_CURRENT_OLD):
                        if status == CONTINUE_CURRENT:
                            cont = False
                        self._evaluate_substring(data, command)

                    n += 1

            except FileNotFoundError as e:
                logger.error(e)
                continue

        return sorted(data)

    def system_info(self):
        """System info algorithm
        Presents basic information about the system
        """
        data = []
        with open(
            os.path.join(
                self.active_controller_directory, "etc", "platform",
                "platform.conf"
            )
        ) as file:
            for line in file:
                if "system_mode" in line:
                    data.append(
                        f"System Mode: "
                        f"{re.match('^system_mode=(.*)', line).group(1)}"
                    )
                elif "system_type" in line:
                    data.append(
                        f"System Type: "
                        f"{re.match('^system_type=(.*)', line).group(1)}"
                    )
                elif "distributed_cloud_role" in line:
                    role = re.match('^distributed_cloud_role=(.*)',
                                    line).group(1)
                    data.append(f"Distributed cloud role: {role}")
                elif "sw_version" in line:
                    data.append(
                        f"SW Version: "
                        f"{re.match('^sw_version=(.*)', line).group(1)}"
                    )
        with open(
            os.path.join(self.active_controller_directory, "etc", "build.info")
        ) as file:
            for line in file:
                if "BUILD_TYPE" in line:
                    data.append(
                        f"Build Type: "
                        f"{re.match('^BUILD_TYPE=(.*)', line).group(1)}"
                    )
                elif re.match("^OS=(.*)", line):
                    data.append(f"OS: {re.match('^OS=(.*)', line).group(1)}")

        return data

    def swact_activity(self):
        """Swact activity algorithm
        Presents all swacting activity in the system
        """
        data = []
        sm_files = []
        sm_customer_files = []
        swact_start = None
        swact_in_progress = False
        swact_end = None

        for _, folder in self.hosts["controllers"].items():
            sm_path = os.path.join(folder, "var", "log", "sm.log")
            sm_files.append(sm_path)
            sm_customer_path = os.path.join(folder, "var", "log",
                                            "sm-customer.log")
            sm_customer_files.append(sm_customer_path)

        sm_substrings = ["Uncontrolled swact", "Swact has started,",
                         "Neighbor (.+) is now in the down",
                         "Service (.+) has reached max failures",
                         "Swact update"]
        data = self.substring(sm_substrings, sm_files)

        for i, line in enumerate(data):
            if "Swact has started," in line and not swact_in_progress:
                swact_in_progress = True
                swact_start = datetime.strptime(line[0:19],
                                                "%Y-%m-%dT%H:%M:%S")
            elif "Swact update" in line and swact_in_progress:
                swact_in_progress = False
                swact_end = datetime.strptime(line[0:19], "%Y-%m-%dT%H:%M:%S")
                line += f" SWACT TOOK {swact_end - swact_start} \n"
                data[i] = line

        sm_customer_substrings = [
            "swact", "active-failed\\s+\\| disabling-failed\\s+\\|"
        ]
        data += self.substring(sm_customer_substrings, sm_customer_files)

        return sorted(data)

    def puppet_errors(self):
        """Puppet errors algorithm
        Presents log errors from puppet logs
        """
        data = []
        for host_type in self.hosts.keys():
            for _, folder in self.hosts[host_type].items():
                puppet_folder = os.path.join(folder, "var", "log", "puppet")
                command = (f"""grep -rh "[m ]Error: " {puppet_folder} """
                           f"""2>/dev/null""")
                self._evaluate_substring(data, command)
        return sorted(data)

    def process_failures(self):
        """Process failures algorithm
        Presents log errors from pmond
        """
        data = []
        files = []
        for host_type in self.hosts.keys():
            for _, folder in self.hosts[host_type].items():
                pmond = os.path.join(folder, "var", "log", "pmond.log")
                files.append(pmond)

        data = self.substring(["Error :"], files)

        return data

    def heartbeat_loss(self):
        """Heartbeat loss algorithm
        Presents all heartbeat loss error messages in the system
        """
        data = []
        hb_files = []

        for _, folder in self.hosts["controllers"].items():
            hb_path = os.path.join(folder, "var", "log", "hbsAgent.log")
            hb_files.append(hb_path)

        hb_substrings = ["Heartbeat Loss"]
        data = self.substring(hb_substrings, hb_files)

        return sorted(data)

    def maintenance_errors(self):
        """Maintenance errors algorithm
        Presents maintenance errors and other relevant log messages in system
        """
        data = []
        mtc_files = []

        for _, folder in self.hosts["controllers"].items():
            agent = os.path.join(folder, "var", "log", "mtcAgent.log")
            mtc_files.append(agent)

        for host_type in self.hosts.keys():
            for _, folder in self.hosts[host_type].items():
                client = os.path.join(folder, "var", "log", "mtcClient.log")
                mtc_files.append(client)

        mtc_substrings = ["Error : ", "Configuration failure",
                          "In-Test Failure", "Loss Of Communication",
                          "Graceful Recovery Wait ",
                          "regained MTCALIVE from host that has rebooted",
                          "Connectivity Recovered ; ",
                          "auto recovery disabled", "Graceful Recovery Failed",
                          "MNFA ENTER", "MNFA EXIT", "MNFA POOL"]
        data = self.substring(mtc_substrings, mtc_files)

        return sorted(data)

    def daemon_failures(self):
        """Daemon failures algorithm
        Presents all failed puppet manifest messages in the system
        """
        data = []
        daemon_files = []

        for host_type in self.hosts.keys():
            for _, folder in self.hosts[host_type].items():
                daemon_path = os.path.join(folder, "var", "log", "daemon.log")
                daemon_files.append(daemon_path)

        daemon_substrings = ["Failed to run the puppet manifest"]
        data = self.substring(daemon_substrings, daemon_files)

        return sorted(data)

    def state_changes(self):
        """State changes algorithm
        Presents all messages in the system regarding the state of hosts
        """
        data = []
        sc_files = []

        for _, folder in self.hosts["controllers"].items():
            sc_path = os.path.join(folder, "var", "log", "mtcAgent.log")
            sc_files.append(sc_path)

        sc_substrings = ["is ENABLED", "allStateChange (.+)locked-disabled"]
        data = self.substring(sc_substrings, sc_files)

        return sorted(data)

    def audit(self, start, end, audit_log_path):
        """Counts audit events in dcmanager within a specified date range

        Parameters:
            start (string)          : start date in YYYY-MM-DD HH:MM:SS format
            end (string)            : end date in YYYY-MM-DD HH:MM:SS format
            audit_log_path (string) : absolute path of augit log file
        """
        if not shutil.which("lnav"):
            raise ValueError("Lnav program not found")

        SECONDS_PER_HOUR = 3600
        fmt = "%Y-%m-%d %H:%M:%S"

        d1 = datetime.strptime(start, fmt)
        d2 = datetime.strptime(end, fmt)
        seconds = (d2 - d1).total_seconds()

        log_texts = [
            "Triggered subcloud audit%",
            "Trigger patch audit%",
            "Trigger load audit%",
            "Triggered firmware audit%",
            "Triggered kubernetes audit%",
            # Counts sum of audits from all subclouds
        ]
        INDEX_MIDDLE_WORD = 1
        data = [("These rates and totals represent the sum of audits from "
                 + "all subclouds")]

        def command(text):

            return (
                f'lnav -R -n -c ";SELECT count(log_body) AS '
                f'{text.split(" ")[INDEX_MIDDLE_WORD]}_total from '
                f'openstack_log WHERE '
                f'(log_time > \\"{start}\\" AND not log_time > \\"{end}\\")'
                f' AND log_body like \\"{text}\\"" "{audit_log_path}"'
            )

        for text in log_texts:
            p = subprocess.Popen(command(text), shell=True,
                                 stdout=subprocess.PIPE)
            for line in p.stdout:
                line = line.decode("utf-8").strip()
                if line.isnumeric():
                    data.append(
                        f"rate "
                        f"{round((int(line)/seconds * SECONDS_PER_HOUR), 3)} "
                        f"per hour.  total: {line}"
                    )
                else:
                    data.append(line)
        return data

    # -----------------------------------

    def run_correlator(self, output_directory, plugin_output_dir):
        """Runs the correlator and prints the results differently based on if
        the tool was run with or without the verbose option

        Parameters:
            output_directory (string)  : directory to place output files from
                                         correlator
            plugin_output_dir (string) : directory with output files from
                                         plugins
        """
        correlator = Correlator(plugin_output_dir)
        failures, events, alarms, state_changes = correlator.run(
            self.opts.hostname)
        failures_len, events_len = len(failures), len(events)
        alarms_len, state_changes_len = len(alarms), len(state_changes)
        failures.append("\nTotal failures found: " + str(failures_len) + "\n")
        events.append("\nTotal events found: " + str(events_len) + "\n")
        alarms.append("\nTotal alarms found: " + str(alarms_len) + "\n")
        state_changes.append("\nTotal state changes found: "
                             + str(state_changes_len) + "\n")

        logger.info("\nRunning correlator...")
        self._create_output_file("correlator_failures", output_directory,
                                 failures, "")
        self._create_output_file("correlator_events", output_directory,
                                 events, "")
        self._create_output_file("correlator_alarms", output_directory,
                                 alarms, "")
        self._create_output_file("correlator_state_changes", output_directory,
                                 state_changes, "")

        if not self.opts.verbose:
            logger.info("Output can be found at "
                        + os.path.relpath(output_directory) + "\n")
            logger.info("Failures: " + str(failures_len))
            for f in failures[:-1]:
                if "Uncontrolled swact" in f:
                    logger.info(f[0:19] + " "
                                + re.findall("active controller:? (.+)\n",
                                             f)[0] + " uncontrolled swact")
                elif "failure on" in f:
                    host = re.findall(r"failure on ([^\s]+) ", f)[0]
                    logger.info(f[0:19] + " " + host + " "
                                + re.findall("^(.+) failure on ",
                                             f[43:])[0].lower() + " failure")
                else:
                    logger.info(f[:-1])
            if failures_len != 0:
                logger.info("\nEvents: " + str(events_len))
            else:
                logger.info("Events: " + str(events_len))
            logger.info("Alarms: " + str(alarms_len))
            logger.info("State Changes: " + str(state_changes_len))
        else:
            logger.info("\nFailures: " + str(failures_len))
            for f in failures[:-1]:
                logger.info(f[:-1])

            # Dictionary to keep track of number of times events happens on
            # each host
            events_summ = {}
            for e in events[:-1]:
                k = e[20:-1].split(" (", 1)[0]
                if not events_summ.get(k):
                    events_summ[k] = 1
                else:
                    events_summ[k] += 1

            if failures_len != 0:
                logger.info("\nEvents: " + str(events_len))
            else:
                logger.info("Events: " + str(events_len))
            for k, v in sorted(events_summ.items()):
                logger.info(k + ": " + str(v) + " time(s)")

            if events_len != 0:
                logger.info("\nAlarms: " + str(alarms_len))
            else:
                logger.info("Alarms: " + str(alarms_len))
            logger.info("The full list of alarms can be found at "
                        + os.path.relpath(output_directory)
                        + "/correlator_alarms")

            # Dictionary to keep track of number of times state changes
            # happens on each host
            state_changes_summ = {}
            for s in state_changes[:-1]:
                k = s[20:-1]
                if "enabled" in k:
                    k = k.split("enabled", 1)[0] + "enabled"
                if not state_changes_summ.get(k):
                    state_changes_summ[k] = 1
                else:
                    state_changes_summ[k] += 1

            if alarms_len != 0:
                logger.info("\nState Changes: " + str(state_changes_len))
            else:
                logger.info("State Changes: " + str(state_changes_len))
            for k, v in sorted(state_changes_summ.items()):
                logger.info(k + ": " + str(v) + " time(s)")

    def _continue(self, file, compressed=False):
        # don't analyze older files, continue with current file
        CONTINUE_CURRENT = 0
        # analyze older files, continue with current file
        CONTINUE_CURRENT_OLD = 1
        # don't analyze current file, continue to older files
        CONTINUE_OLD = 2

        # check date of first log event and compare with provided
        # start, end dates
        first = ""

        if not compressed:
            with open(file) as f:
                line = f.readline()
                first = line[0:19]
        else:
            with gzip.open(file, "rb") as f:
                line = f.readline().decode("utf-8")
                first = line[0:19]
        try:
            datetime.strptime(line[0:19], "%Y-%m-%dT%H:%M:%S")
            first = line[0:19]
        except ValueError:
            return CONTINUE_CURRENT_OLD

        if first < self.opts.start:
            return CONTINUE_CURRENT
        elif first < self.opts.end and first > self.opts.start:
            return CONTINUE_CURRENT_OLD
        elif first > self.opts.end:
            return CONTINUE_OLD

    def _evaluate_substring(self, data, command):
        p = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE)
        for line in p.stdout:
            line = line.decode("utf-8")
            # different date locations for log events
            dates = [line[0:19], line[2:21]]
            for date in dates:
                try:
                    datetime.strptime(date, "%Y-%m-%dT%H:%M:%S")
                    if date > self.opts.start and date < self.opts.end:
                        if line[0] == "|":  # sm-customer.log edge case
                            line = line[1:].strip()
                            line = re.sub("\\s+", " ", line)
                        data.append(line)
                    break
                except ValueError:
                    if date == dates[-1]:
                        data.append(line)

    def _extract_subfunction(self, host_info_path):
        GROUP_ONE = 1
        with open(host_info_path) as file:
            for line in file:
                hostname_match = re.match(
                    r"\s*hostname =>\s*\"?([^\"]*)(\n|\"\s*,?\s*\n)", line)
                subfunction_match = re.match(
                    r"\s*subfunction =>\s*\"?([^\"]*)(\n|\"\s*,?\s*\n)", line)
                if subfunction_match:
                    subfunction = subfunction_match.group(GROUP_ONE)
                if hostname_match:
                    hostname = hostname_match.group(GROUP_ONE)
        return hostname, subfunction

    def _create_output_file(self, filename, directory, data, processing):
        with open(os.path.join(directory, filename), "w") as file:
            for i in data:
                if i[-1] == "\n":
                    file.write(i)
                else:
                    file.write(i + "\n")
        if self.opts.verbose:
            output = ("output at "
                      + os.path.relpath(os.path.join(directory, filename)))
            if processing == "":
                logger.info(output)
            else:
                logger.info(processing + ", " + output)
        elif processing != "":
            logger.info(processing)
