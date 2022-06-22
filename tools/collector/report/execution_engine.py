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
########################################################################

from datetime import datetime
import gzip
import logging
import os
import re
import shutil
import subprocess

import algorithms


logger = logging.getLogger(__name__)


class ExecutionEngine:
    def __init__(self, opts):
        """Constructor for the ExecutionEngine class

        Parameters:
            opts (dictionary): Options from command line
        """
        self.opts = opts
        self.hosts = {"controllers": {}, "workers": {}, "storages": {}}
        self.active_controller_directory = None

        for folder in (f.path for f in os.scandir(self.opts.directory)):
            database_path = os.path.join(folder, "var", "extra", "database")
            host_info_path = os.path.join(folder, "var", "extra", "host.info")

            if os.path.isdir(database_path) and os.listdir(database_path):
                self.active_controller_directory = folder

            if os.path.exists(host_info_path):
                hostname, subfunction = self._extract_subfunction(host_info_path)
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

        for plugin in plugins:
            logger.info(f"Processing plugin: {os.path.basename(plugin.file)}")
            hosts = {}
            if (
                plugin.state["hosts"] and len(plugin.state["hosts"]) >= 1
            ):  # if host list is given
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
                        try:
                            events = self.substring(
                                plugin.state["substring"],
                                [
                                    os.path.join(folderpath, file)
                                    for file in plugin.state["files"]
                                ],
                            )
                        except FileNotFoundError as e:
                            logger.error(e)
                            continue

                        # creating output file
                        output_file = os.path.join(
                            output_directory,
                            f"{hostname}_{os.path.basename(plugin.file)}_{plugin.state['algorithm']}",
                        )
                        logger.info("output at " + output_file)
                        with open(output_file, "w") as file:
                            file.write(
                                f"Date range: {self.opts.start} until {self.opts.end}\n"
                            )
                            file.write(
                                f"substrings: {' '.join(plugin.state['substring'])}\n"
                            )
                            for line in events:
                                file.write(line + "\n")
            else:
                if plugin.state["algorithm"] == algorithms.SYSTEM_INFO:
                    info = self.system_info()
                    system_info_output = os.path.join(output_directory, "system_info")
                    with open(system_info_output, "w") as file:
                        for i in info:
                            file.write(i + "\n")

                        for k, v in self.hosts.items():
                            file.write(f"{k}: {','.join(v.keys())}\n")
                    logger.info("output at " + system_info_output)

                elif plugin.state["algorithm"] == algorithms.AUDIT:
                    hosts = {}
                    hosts.update(self.hosts["workers"])
                    hosts.update(self.hosts["storages"])
                    hosts.update(self.hosts["controllers"])

                    for hostname, folderpath in hosts.items():
                        self._create_output_file(
                            f"{hostname}_audit",
                            output_directory,
                            self.audit(
                                plugin.state["start"],
                                plugin.state["end"],
                                os.path.join(
                                    folderpath, "var", "log", "dcmanager", "audit.log"
                                ),
                            ),
                        )

                elif plugin.state["algorithm"] == algorithms.SWACT:
                    self._create_output_file(
                        "swact_activity", output_directory, self.swact()
                    )

                elif plugin.state["algorithm"] == algorithms.PUPPET:
                    self._create_output_file(
                        "puppet_errors", output_directory, self.puppet()
                    )

                elif plugin.state["algorithm"] == algorithms.PROCESS_FAILURE:
                    self._create_output_file(
                        "process_failures", output_directory, self.process_failure()
                    )

                elif plugin.state["algorithm"] == algorithms.ALARM:
                    alarms, logs = self.alarm(
                        plugin.state["alarm_ids"], plugin.state["entity_ids"]
                    )
                    alarm_output = os.path.join(output_directory, "alarm")
                    log_output = os.path.join(output_directory, "log")
                    os.makedirs(os.path.dirname(log_output), exist_ok=True)

                    # creating output alarm file
                    with open(alarm_output, "w") as file:
                        for k, v in alarms.items():
                            file.write(f"{k} {v['count']}\n")
                        file.write("\n")
                        for k, v in alarms.items():
                            file.write(f"{k}\n")
                            for date in v["dates"]:
                                file.write(f"   {date}\n")

                    # creating output log file
                    with open(log_output, "w") as file:
                        for k, v in logs.items():
                            file.write(f"{k} {v['count']}\n")
                        file.write("\n")
                        for k, v in logs.items():
                            file.write(f"{k}\n")
                            for date in v["dates"]:
                                file.write(f"   {date}\n")
                    logger.info("output at " + alarm_output)
                    logger.info("output at " + log_output)

    # Built-in algorithms ------------------------------
    def alarm(self, alarm_ids=[], entity_ids=[]):
        """Alarm algorithm
        Gathers list of alarms and customer logs

        Parameters:
            alarm_ids (string list) : List of alarm id patterns to search for
            entity_ids (string list): List of entity id patterns to search for
        """
        alarm_data = {}
        log_data = {}
        with open(
            os.path.join(
                self.active_controller_directory,
                "var",
                "extra",
                "database",
                "fm.db.sql.txt",
            )
        ) as file:
            start = False
            for line in file:
                # start of event log
                if "COPY event_log" in line:
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
                    if self.opts.start <= entry_date and entry_date <= self.opts.end:
                        # if the alarm is not in the user specified list of alarm or entity ids
                        for id in alarm_ids:
                            if id in alarm_id:
                                break
                        else:
                            if len(alarm_ids) > 0:
                                continue

                        for entity in entity_ids:
                            if entity in entity_id:
                                break
                        else:
                            if len(entity_ids) > 0:
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
                                alarm_info["count"] += 1
                                alarm_info["dates"].append(f"{alarm_date} {action}")
                        except KeyError:
                            if entry[6] != "log":
                                alarm_data[f"{alarm_id} {entity_id} {severity}"] = {
                                    "count": 1,
                                    "dates": [f"{alarm_date} {action}"],
                                }
                            else:
                                log_data[f"{alarm_id} {entity_id} {severity}"] = {
                                    "count": 1,
                                    "dates": [alarm_date],
                                }

        for _, v in alarm_data.items():
            v["dates"] = sorted(v["dates"])

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
        CONTINUE_CURRENT = 0  # don't analyze older files, continue with current file
        CONTINUE_CURRENT_OLD = 1  # analyze older files, continue with current file

        data = []
        for file in files:
            if not os.path.exists(file):
                raise FileNotFoundError(f"File not found: {file}")
            cont = True
            # Searching through file
            command = f"""grep -Ea "{'|'.join(s for s in substr)}" {file}"""
            status = self._continue(file)

            if (
                status == CONTINUE_CURRENT or status == CONTINUE_CURRENT_OLD
            ):  # continue with current file
                if status == CONTINUE_CURRENT:
                    cont = False
                self._evaluate_substring(data, command)

            # Searching through rotated log files
            n = 1
            while os.path.exists(f"{file}.{n}.gz") and cont:
                command = f"""zgrep -E "{'|'.join(s for s in substr)}" {file}.{n}.gz"""
                status = self._continue(f"{file}.{n}.gz", compressed=True)

                if status == CONTINUE_CURRENT or status == CONTINUE_CURRENT_OLD:
                    if status == CONTINUE_CURRENT:
                        cont = False
                    self._evaluate_substring(data, command)

                n += 1

        return sorted(data)

    def system_info(self):
        """System info algorithm
        Presents basic information about the system
        """
        data = []
        with open(
            os.path.join(
                self.active_controller_directory, "etc", "platform", "platform.conf"
            )
        ) as file:
            for line in file:
                if "system_mode" in line:
                    data.append(
                        f"System Mode: {re.match('^system_mode=(.*)', line).group(1)}"
                    )
                elif "system_type" in line:
                    data.append(
                        f"System Type: {re.match('^system_type=(.*)', line).group(1)}"
                    )
                elif "distributed_cloud_role" in line:
                    data.append(
                        f"Distributed cloud role: {re.match('^distributed_cloud_role=(.*)', line).group(1)}"
                    )
                elif "sw_version" in line:
                    data.append(
                        f"SW Version: {re.match('^sw_version=(.*)', line).group(1)}"
                    )
        with open(
            os.path.join(self.active_controller_directory, "etc", "build.info")
        ) as file:
            for line in file:
                if "BUILD_TYPE" in line:
                    data.append(
                        f"Build Type: {re.match('^BUILD_TYPE=(.*)', line).group(1)}"
                    )
                elif re.match("^OS=(.*)", line):
                    data.append(f"OS: {re.match('^OS=(.*)', line).group(1)}")

        return data

    def swact(self):
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

        sm_substrings = ["Swact has started,", "Swact update"]
        data = self.substring(sm_substrings, sm_files)

        for i, line in enumerate(data):
            if "Swact has started," in line and not swact_in_progress:
                swact_in_progress = True
                swact_start = datetime.strptime(line[0:19], "%Y-%m-%dT%H:%M:%S")
            elif "Swact update" in line and swact_in_progress:
                swact_in_progress = False
                swact_end = datetime.strptime(line[0:19], "%Y-%m-%dT%H:%M:%S")
                line += f" SWACT TOOK {swact_end - swact_start} \n"
                data[i] = line

        for _, folder in self.hosts["controllers"].items():
            sm_customer_path = os.path.join(folder, "var", "log", "sm-customer.log")
            sm_customer_files.append(sm_customer_path)

        sm_customer_substrings = ["swact"]
        data += self.substring(sm_customer_substrings, sm_customer_files)

        return sorted(data)

    def puppet(self):
        """Puppet error algorithm
        Presents log errors from puppet logs
        """
        data = []
        for _, folder in self.hosts["controllers"].items():
            puppet_folder = os.path.join(folder, "var", "log", "puppet")
            command = f"grep -rh 'Error:' {puppet_folder}"
            self._evaluate_substring(data, command)
        return sorted(data)

    def process_failure(self):
        """Process failure algorithm
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
        data = ["These rates and totals represent the sum of audits from all subclouds"]

        def command(text):

            return (
                f'lnav -R -n -c ";SELECT count(log_body) AS {text.split(" ")[INDEX_MIDDLE_WORD]}_total'
                f' from openstack_log WHERE (log_time > \\"{start}\\" AND not log_time > \\"{end}\\")'
                f' AND log_body like \\"{text}\\"" "{audit_log_path}"'
            )

        for text in log_texts:
            p = subprocess.Popen(command(text), shell=True, stdout=subprocess.PIPE)
            for line in p.stdout:
                line = line.decode("utf-8").strip()
                if line.isnumeric():
                    data.append(
                        f"rate {round((int(line)/seconds * SECONDS_PER_HOUR), 3)} per hour.  total: {line}"
                    )
                else:
                    data.append(line)
        return data

    # -----------------------------------

    def _continue(self, file, compressed=False):
        CONTINUE_CURRENT = 0  # don't analyze older files, continue with current file
        CONTINUE_CURRENT_OLD = 1  # analyze older files, continue with current file
        CONTINUE_OLD = 2  # don't analyze current file, continue to older files

        # check date of first log event and compare with provided start end dates
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
            dates = [line[0:19], line[2:21]]  # different date locations for log events
            for date in dates:
                try:
                    datetime.strptime(date, "%Y-%m-%dT%H:%M:%S")
                    if date > self.opts.start and date < self.opts.end:
                        if line[0] == "|":  # sm-customer.log edge case
                            line = line.replace("|", "").strip()
                            line = re.sub("\s+", " ", line)
                        data.append(line)
                    break
                except ValueError:
                    if date == dates[-1]:
                        data.append(line)

    def _extract_subfunction(self, host_info_path):
        GROUP_ONE = 1
        with open(host_info_path) as file:
            for line in file:
                hostname_match = re.match("^hostname => (.+)", line)
                subfunction_match = re.match("^subfunction => (.+)", line)
                if subfunction_match:
                    subfunction = subfunction_match.group(GROUP_ONE)
                if hostname_match:
                    hostname = hostname_match.group(GROUP_ONE)
        return hostname, subfunction

    def _create_output_file(self, filename, directory, events):
        with open(os.path.join(directory, filename), "w") as file:
            for i in events:
                file.write(i + "\n")
        logger.info("output at " + os.path.join(directory, filename))
