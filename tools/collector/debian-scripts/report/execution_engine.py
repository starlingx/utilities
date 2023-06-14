########################################################################
#
# Copyright (c) 2022 - 2023 Wind River Systems, Inc.
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
# Futures:
#
# 1. Improve how report determines the active controller.
#    Specifically what controller was active at the time of detected
#    failure rather than what controller was active when collect ran.
#
# 2. Consider running plugins in parallel threads
#
########################################################################

import logging
import mmap
import os
import re
import subprocess
import sys
import tarfile

import algorithms
from correlator import Correlator
from plugin_algs.alarm import alarm
from plugin_algs.audit import audit
from plugin_algs.daemon_failures import daemon_failures
from plugin_algs.heartbeat_loss import heartbeat_loss
from plugin_algs.maintenance_errors import maintenance_errors
from plugin_algs.process_failures import process_failures
from plugin_algs.puppet_errors import puppet_errors
from plugin_algs.state_changes import state_changes
from plugin_algs.substring import substring
from plugin_algs.swact_activity import swact_activity
from plugin_algs.system_info import system_info

# don't generate __pycache__ dir and files
sys.dont_write_bytecode = True

logger = logging.getLogger(__name__)

# regex expression used to get the hostname from the host dir name
# eg: chops '_20221201.213332' off of controller-0_20221201.213332
regex_chop_bundle_date = r"_\d{8}\.\d{6}"
regex_get_bundle_date = r".*_\d{8}\.\d{6}$"


class ExecutionEngine:
    def __init__(self, opts, input_dir, output_dir):
        """Constructor for the ExecutionEngine class

        Parameters:
            opts (dictionary): Options from command line
            output_dir (string): directory to put output files
        """
        # don't generate __pycache__ dir and files
        sys.dont_write_bytecode = True
        self.opts = opts
        self.hosts = {"controllers": {}, "workers": {}, "storages": {}}
        self.active_controller_directory = None
        self.active_controller_hostname = None
        self.host_dirs = []
        self.hostnames = []

        if not os.path.isdir(input_dir):
            logger.error("Error: Invalid input directory: %s", input_dir)
            sys.exit("... exiting")
        self.input_dir = input_dir
        if not os.path.isdir(output_dir):
            logger.error("Error: Invalid output directory : %s", output_dir)
            sys.exit("... exiting")
        self.output_dir = output_dir

        # Uncompresses host tar files if not already done
        with open(os.path.join(output_dir, "untar.log"), "a") as logfile:

            # Now extract the tarballs
            for obj in (os.scandir(self.input_dir)):
                # files to ignore
                if obj.name == "report_tool.tgz":
                    continue

                info = os.path.splitext(obj.name)
                if (obj.is_file() and tarfile.is_tarfile(obj.path) and not
                        os.path.isdir(os.path.join(self.input_dir, info[0]))):
                    try:
                        logger.info("extracting : %s", obj.path)
                        subprocess.run(["tar", "xzfC", obj.path,
                                        self.input_dir],
                                       stderr=logfile, check=True)
                    except subprocess.CalledProcessError as e:
                        logger.error(e)

        # Determine the active controller and load system info from it.
        for folder in (f.path for f in os.scandir(self.input_dir)):
            basename = os.path.basename(folder)

            # Ignore all directories that are not a properly dated
            # collect file
            if not re.match(regex_get_bundle_date, basename):
                continue

            # skip over files (the tarballs)
            if not os.path.isdir(folder):
                continue

            logger.debug("base folder: %s", os.path.basename(folder))

            # Get the hostname from the host folder
            hostname = re.sub(regex_chop_bundle_date, "", basename)
            self.hostnames.append(hostname)

            host_dir = folder
            self.host_dirs.append(host_dir)
            logger.debug("Host Dirs: %s", self.host_dirs)

            # build up a list of hosts. save host folder path based on nodetype
            hostinfo_path = os.path.join(host_dir, "var/extra/host.info")
            if os.path.exists(hostinfo_path):
                hostname, subfunction = self._extract_subfunction(
                    hostinfo_path)
                if "controller" in subfunction:
                    self.hosts["controllers"][hostname] = folder
                elif "worker" in subfunction:
                    self.hosts["workers"][hostname] = folder
                elif "storage" in subfunction:
                    self.hosts["storages"][hostname] = folder

            # skip non controller hosts since that could not be active
            if hostname[0:10] != "controller":
                continue

            logger.debug("searching for active controller: %s" % hostname)
            if os.path.isdir(host_dir):
                logger.debug("... checking %s" % hostname)
                extra_path = os.path.join(host_dir, "var/extra")

                # don't analyse a directory that doesn't contain
                # a 'var/extra' dir.
                if not os.path.exists(extra_path):
                    logger.warning("%s is missing var/extra" % hostname)
                    continue

                database_path = os.path.join(host_dir, "var/extra/database")
                if os.path.exists(database_path):
                    if os.listdir(database_path):
                        logger.info("Active Ctrl: %s" % hostname)
                        self.active_controller_directory = folder
                        self.active_controller_hostname = hostname

        if not len(self.host_dirs):
            logger.error("Error: No host bundles found in %s" % input_dir)
            files = []
            for folder in (f.path for f in os.scandir(input_dir)):
                files.append(os.path.basename(folder))
            if files:
                logger.error("... content: %s" % files)
            sys.exit("")

        if not self.active_controller_directory:
            logger.warning("Active Ctrl: NOT FOUND")

    def execute(self, plugins, output_dir):
        """Run a list of plugins

        Parameters:
            plugins (Plugin list): List of plugins to run
            output_dir (string): directory to put output files

        Errors:
            FileNotFoundError
        """
        plugin_output_dir = os.path.join(output_dir, "plugins")
        os.makedirs(plugin_output_dir, exist_ok=True)

        if self.opts.verbose:
            logger.info("Output files for plugins can be found at " +
                        os.path.abspath(plugin_output_dir))
        if self.opts.debug:
            logger.debug("Processing Plugins for hosts: %s", self.host_dirs)

        for plugin in plugins:
            processing = "Processing plugin: " + os.path.basename(plugin.file)
            hosts = {}
            if (
                plugin.state["hosts"] and len(plugin.state["hosts"]) >= 1
            ):  # if host list is given
                if self.opts.debug:
                    logger.debug(processing)

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
                        events = substring(
                            self.opts.start, self.opts.end,
                            plugin.state["substring"],
                            [
                                os.path.join(folderpath, file)
                                for file in plugin.state["files"]
                            ],
                            plugin.state["exclude"],
                        )

                        # creating output file
                        output_file = os.path.join(
                            plugin_output_dir,
                            f"substring_{hostname}",
                        )
                        if self.opts.verbose:
                            logger.info("... output at " +
                                        os.path.abspath(output_file))
                        if events:
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
                    # Get system info of the active controller first
                    # and then put the system info of each host in the
                    # system info output folder.
                    system_info_output = os.path.join(plugin_output_dir,
                                                      "system_info")
                    if os.path.exists(system_info_output):
                        os.remove(system_info_output)

                    hostname = None
                    host_dir = None
                    if self.active_controller_directory is None:
                        hostname = re.sub(regex_chop_bundle_date, "",
                                          os.path.basename(self.host_dirs[0]))
                        host_dir = self.host_dirs[0]
                    else:
                        hostname = self.active_controller_hostname
                        host_dir = self.active_controller_directory

                    system_info(hostname, host_dir,
                                system_info_output,
                                self.hosts, True)

                    for host_dir in self.host_dirs:
                        if host_dir != self.active_controller_directory:
                            hostname = re.sub(regex_chop_bundle_date, "",
                                              os.path.basename(host_dir))
                            system_info(hostname,
                                        host_dir,
                                        system_info_output,
                                        None,
                                        False)

                elif plugin.state["algorithm"] == algorithms.AUDIT:
                    hosts = {}
                    hosts.update(self.hosts["workers"])
                    hosts.update(self.hosts["storages"])
                    hosts.update(self.hosts["controllers"])

                    for hostname, folderpath in hosts.items():
                        self._create_output_file(
                            f"{hostname}_audit",
                            plugin_output_dir,
                            audit(
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
                        swact_activity(self.hosts, self.opts.start,
                                       self.opts.end),
                        processing
                    )

                elif plugin.state["algorithm"] == algorithms.PUPPET_ERRORS:
                    self._create_output_file(
                        "puppet_errors", plugin_output_dir,
                        puppet_errors(self.hosts, self.opts.start,
                                      self.opts.end),
                        processing
                    )

                elif plugin.state["algorithm"] == algorithms.PROCESS_FAILURES:
                    self._create_output_file(
                        "process_failures", plugin_output_dir,
                        process_failures(self.hosts, self.opts.start,
                                         self.opts.end),
                        processing
                    )

                elif plugin.state["algorithm"] == algorithms.ALARM:
                    for host_dir in self.host_dirs:

                        alarms, logs = alarm(
                            host_dir,
                            self.opts.start, self.opts.end,
                            plugin.state["alarm_exclude"],
                            plugin.state["entity_exclude"]
                        )
                        if alarms is None and logs is None:
                            continue

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
                            logger.info(processing)
                        elif self.opts.debug:
                            logger.debug(processing + ", output at " +
                                         os.path.abspath(alarm_output) +
                                         ", " + os.path.abspath(log_output))

                elif plugin.state["algorithm"] == algorithms.HEARTBEAT_LOSS:
                    self._create_output_file(
                        "heartbeat_loss", plugin_output_dir,
                        heartbeat_loss(self.hosts, self.opts.start,
                                       self.opts.end),
                        processing
                    )
                elif plugin.state["algorithm"] == algorithms.MAINTENANCE_ERR:
                    self._create_output_file(
                        "maintenance_errors", plugin_output_dir,
                        maintenance_errors(self.hosts, self.opts.start,
                                           self.opts.end,
                                           plugin.state["exclude"]),
                        processing
                    )
                elif plugin.state["algorithm"] == algorithms.DAEMON_FAILURES:
                    self._create_output_file(
                        "daemon_failures", plugin_output_dir,
                        daemon_failures(self.hosts, self.opts.start,
                                        self.opts.end,
                                        plugin.state["exclude"]),
                        processing
                    )
                elif plugin.state["algorithm"] == algorithms.STATE_CHANGES:
                    self._create_output_file(
                        "state_changes", plugin_output_dir,
                        state_changes(self.hosts, self.opts.start,
                                      self.opts.end),
                        processing
                    )

        # Dump a summary of data found by the plugins
        if os.path.exists(plugin_output_dir):

            # Print a summary of the logs/data gathers by the plugins
            empty_files = ""
            logger.info("")
            logger.info("Plugin Results:")
            logger.info("")
            lines = []
            for fn in os.listdir(plugin_output_dir):
                filename = os.path.join(plugin_output_dir, fn)
                with open(filename, "r+") as f:
                    # Show how much data is in each plugins output file
                    if os.path.isfile(filename) and os.path.getsize(filename):
                        buf = mmap.mmap(f.fileno(), 0)
                        entries = 0
                        readline = buf.readline
                        while readline():
                            entries += 1
                        lines.append("%5d %s" % (entries, filename))
                    else:
                        empty_files += fn + " "

            # Sort the lines based on the numeric value
            sorted_lines = sorted(lines, key=lambda x: int(x.split()[0]),
                                  reverse=True)

            for line in sorted_lines:
                logger.info(line)

            if empty_files:
                logger.info("")
                logger.info("... nothing found by plugins: %s" % empty_files)
        else:
            logger.error("Error: Plugin output dir missing: %s" %
                         plugin_output_dir)
            sys.exit("... exiting")

        # Running the correlator and printing the output from it
        self.run_correlator(output_dir, plugin_output_dir)

    # -----------------------------------

    def run_correlator(self, output_dir, plugin_output_dir):
        """Runs the correlator and prints the results differently based on if
        the tool was run with or without the verbose option

        Parameters:
            output_dir (string)  : directory to place output files from
                                         correlator
            plugin_output_dir (string) : directory with output files from
                                         plugins
        """

        # logger.info("Correlator Output Dir: %s", output_dir)
        # logger.info("Correlator Plugin Dir: %s", plugin_output_dir)

        correlator = Correlator(plugin_output_dir)
        failures, events, alarms, state_changes = correlator.run(
            self.opts.hostname)
        failures_len, events_len = len(failures), len(events)
        alarms_len, state_changes_len = len(alarms), len(state_changes)
        failures.append("\nTotal failures found: " + str(failures_len) + "\n")
        events.append("\nTotal events found: " + str(events_len) + "\n")
        alarms.append("\nTotal alarms found: " + str(alarms_len) + "\n")
        state_changes.append("\nTotal state changes found: " +
                             str(state_changes_len) + "\n")
        logger.info("")
        logger.info("Correlated Results:")
        logger.info("")
        self._create_output_file("failures", output_dir,
                                 failures, "")
        self._create_output_file("events", output_dir,
                                 events, "")
        self._create_output_file("alarms", output_dir,
                                 alarms, "")
        self._create_output_file("state_changes", output_dir,
                                 state_changes, "")

        max = 0
        for sl in [events_len, alarms_len, state_changes_len, failures_len]:
            if len(str(sl)) > max:
                max = len(str(sl))
        if not self.opts.verbose:
            logger.info("Events       : " + str(events_len) +
                        " " * (max - len(str(events_len))) +
                        " " + output_dir + "/events")
            logger.info("Alarms       : " + str(alarms_len) +
                        " " * (max - len(str(alarms_len))) +
                        " " + output_dir + "/alarms")
            logger.info("State Changes: " + str(state_changes_len) +
                        " " * (max - len(str(state_changes_len))) +
                        " " + output_dir + "/state_changes")
            logger.info("Failures     : " + str(failures_len) +
                        " " * (max - len(str(failures_len))) +
                        " " + output_dir + "/failures")
            for f in failures[:-1]:
                if "Uncontrolled swact" in f:
                    logger.info(f[0:19] + " " +
                                re.findall("active controller:? (.+)\n",
                                f)[0] + " uncontrolled swact")
                elif "failure on" in f:
                    host = re.findall(r"failure on ([^\s]+) ", f)[0]
                    logger.info(f[0:19] + " " + host + " " +
                                re.findall("^(.+) failure on ",
                                f[43:])[0].lower() + " failure")
                else:
                    logger.info(f[:-1])
        else:

            # Dictionary to keep track of number of times events happens on
            # each host
            events_summ = {}
            for e in events[:-1]:
                k = e[20:-1].split(" (", 1)[0]
                if not events_summ.get(k):
                    events_summ[k] = 1
                else:
                    events_summ[k] += 1
            logger.info("\nEvents: " + str(events_len))
            for k, v in sorted(events_summ.items()):
                logger.info(k + ": " + str(v) + " time(s)")

            logger.info("\nAlarms: " + str(alarms_len))
            logger.info("The full list of alarms can be found at " +
                        os.path.abspath(output_dir) +
                        "/alarms")

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

            logger.info("\nState Changes: " + str(state_changes_len))
            for k, v in sorted(state_changes_summ.items()):
                logger.info(k + ": " + str(v) + " time(s)")

            logger.info("\nFailures     : " + str(failures_len))
            for f in failures[:-1]:
                logger.info(f[:-1])

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
            output = ("... output at " +
                      os.path.abspath(os.path.join(directory, filename)))
            if processing == "":
                logger.info(output)
            else:
                logger.info(processing + ", " + output)
