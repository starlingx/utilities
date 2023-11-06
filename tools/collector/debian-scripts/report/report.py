#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2022 - 2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# Description: The Report tool is used to gather relevant log, events
#              and information about the system from a collect bundle
#              and present that data for quick / easy issue analysis.
#
# Overview:
#
# The report tool implements an 'Execution Engine' runs 'Algorithms'
# against 'Plugins' to gather logs, events & system information that
# the 'Correlator' analyzes to produce a summary of events, alarms,
# state changes and failures found by the plugins.
#
# Report Tool: report.py
#
# Parses command line arguments, sets up logging, extracts the top
# level collect bundle, initializes the execution engine, loads the
# plugins and invokes the execution engine.
#
# Execution Engine: execution_engine.py
#
# Initialization extracts the bundle's host tarballs, finds the
# active controller and host types from each tarball. When executed
# runs the algorithms specified by each of the loaded plugins and
# then calls the correlator.
#
# Correlator: correlator.py
#
# Analyzes the data and logs gathered by the plugins and produces
# and displays a report_analysis that contains a summary of:
#
# - Alarms   ... when and what alarms were found to have occurred
# - Events   ... noteworthy events; Graceful Recovery, MNFA
# - Failures ... host or service management failures; swacts
# - State    ... summary of host state changes; enable -> disable
#
# Algorithms: algorithms.py
#
# The report tool supports a set of built-in algorithms used to
# gather collect bundle events, logs and data.
#
# The following algorithms in 'plugin_algs' directory are supported:
#
# - audit.py  ............. counts dcmanager audit events
# - alarm.py  ............. summarizes alarm state transitions and when
# - heartbeat_loss.py ..... gathers maintenance heartbeat failures
# - daemon_failures.py .... gathers various common daemon log errors
# - maintenance_errors.py . gathers maintenance error logs
# - puppet_errors.py ...... gathers puppet failures and logs
# - state_changes.py ...... gathers a summary of host state changes
# - swact_activity.py ..... identifies various swact occurrences
# - process_failures.py ... gathers pmond process failure logs
# - substring.py    ....... gathers substring plugin specified info
# - system_info.py ........ gathers system info ; type, mode, etc
#
# Plugins: plugins.py
#
# Plugins are small label based text files that specify an algorithm
# and other applicable labels used to find specific data, logs or
# events for that plugin.
#
# The following default internal plugins are automatically included
# with the report tool stored in the 'plugins' directory.
#
# - alarm      ............ specifies alarms to look for
# - audit    .............. find dcmanager audit events
# - daemon_failures ....... runs the daemon failure algorithm
# - heartbeat_loss ........ runs the mtce heartbeat loss algorithm
# - maintenance_errors .... find specific maintenance logs
# - process_failures ...... find pmon or sm process failures
# - puppet_errors ......... find configuration failure puppet logs
# - state_changes ......... find host state changes
# - substring ............. find logs containing named substrings
# - swact_activity ........ find swact failure and events
# - system_info ........... gather system information
#
# The report tool will also run additional (optional) user defined
# plugins developed and placed in the localhost's filesystem at
# /etc/collect/plugins.
#
# Typical Usage:
#
#  command line                      functionality
#  -------------------------------   ----------------------------------
# > report.py --help                  - help message
# > report.py -b /path/to/bundle      - path to dir containing host tarballs
# > report.py -d /path/to/bundle      - path to dir containing tar bundle(s)
# > report.py -f /path/to/bundle.tar  - specify path to a bundle tar file
# > report.py -d <dir> [plugin ...]   - Run only specified plugins
# > report.py -d <dir> <algs> [labels]- Run algorithm with labels
# > report.py <algorithm> --help      - algorithm specific help
#
#    See --help output for a complete list of full and abbreviated
#    command line options and examples of plugins.
#
# Refer to README file for more usage and output examples
#######################################################################

import argparse
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import logging
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time

# internal imports
import algorithms
from execution_engine import ExecutionEngine
from plugin import Plugin
import render

# Globals
now = datetime.now(timezone.utc)
report_dir = os.path.dirname(os.path.realpath(__file__))
analysis_folder_name = "report_analysis"
plugins = []
output_dir = None
tmp_report_log = tempfile.mkstemp()


parser = argparse.ArgumentParser(
    description="Report Tool:",
    epilog="Analyzes data collected by the plugins and produces a "
    "report_analysis stored with the collect bundle. The report tool "
    "can be run either on or off system by specifying the bundle to "
    "analyze using the --directory, --bundle or --file command options.",
)

parser.add_argument(
    "--debug",
    action="store_true",
    help="Enable debug logs",
)

parser.add_argument(
    "--bundle", "-b",
    default="",
    required=False,
    help="Specify the full path to a directory containing a collect "
    "bundle to analyze. Use this option when pointing to a directory "
    "with host .tgz files that are already extracted from a tar file.",
)

parser.add_argument(
    "--directory", "-d",
    default="",
    required=False,
    help="Specify the full path to a directory containing collect "
    "bundles to analyze.",
)

parser.add_argument(
    "--file", "-f",
    default="",
    required=False,
    help="Specify the path to and filename of the tar bundle to analyze",
)

parser.add_argument(
    "--end", "-e",
    default=datetime.strftime(now + timedelta(days=1), "%Y%m%d"),
    help="Specify an end date in YYYYMMDD format for analysis "
    "(default: current date)",
)

parser.add_argument(
    "--hostname",
    default="all",
    help="Specify hostname to produce correlated results for "
    "(default: all hosts)",
)

parser.add_argument(
    "--plugin", "-p",
    default=None,
    nargs="*",
    help="Specify a space delimited list of plugins to run "
    "(default: all plugins)",
)

parser.add_argument(
    "--start", "-s",
    default="20000101",
    help="Specify a start date in YYYYMMDD format for analysis "
    "(default:20000101)",
)

parser.add_argument(
    "--state",
    action="store_true",
    help="Debug option to dump object state during execution",
)

parser.add_argument(
    "--verbose", "-v",
    action="store_true",
    help="Enable verbose output",
)

subparsers = parser.add_subparsers(help="algorithms", dest="algorithm")

# substring algorithm arguments
parser_substring = subparsers.add_parser(
    "substring",
    formatter_class=argparse.RawTextHelpFormatter,
    help="""Searches through specified files for lines containing specified
            substring. There will be an output file for each host of the host
            type specified.""",
    epilog="Plugin file example:\n"
    "   algorithm=substring\n"
    "   files=var/log/mtcAgent.log, var/log/sm.log\n"
    "   hosts=controllers\n"
    "   substring=operation failed\n"
    "   substring=Failed to send message",
)
substring_required = parser_substring.add_argument_group("required arguments")
substring_required.add_argument(
    "--files",
    required=True,
    nargs="+",
    help="Files to perform substring analysis on (required)",
)
substring_required.add_argument(
    "--substring", nargs="+", required=True,
    help="Substrings to search for (required)"
)
substring_required.add_argument(
    "--hosts",
    choices=["controllers", "workers", "storages", "all"],
    required=True,
    nargs="+",
    help="Host types to perform analysis on (required)",
)


# alarm algorithm arguments
parser_alarm = subparsers.add_parser(
    "alarm",
    formatter_class=argparse.RawTextHelpFormatter,
    help="Searches through fm.db.sql.txt for alarms and logs except for those "
    "specified. There are 2 output files: 'alarm', and 'log'",
    epilog="Plugin file example:\n"
    "   algorithm=alarm\n"
    "   alarm_exclude=400., 800.\n"
    "   entity_exclude=subsystem=vim\n",
)
parser_alarm.add_argument(
    "--alarm_exclude",
    nargs="+",
    required=False,
    default=[],
    help="Alarm id patterns to not search for (not required)",
)
parser_alarm.add_argument(
    "--entity_exclude",
    nargs="+",
    required=False,
    default=[],
    help="Entity id patterns to not search for (not required)",
)

# system info algorithm
parser_system_info = subparsers.add_parser(
    "system_info",
    formatter_class=argparse.RawTextHelpFormatter,
    help="Presents information about the system",
    epilog="Plugin file example:\n" "   algorithm=system_info\n",
)

# swact activity algorithm
parser_swact_activity = subparsers.add_parser(
    "swact_activity",
    formatter_class=argparse.RawTextHelpFormatter,
    help="Presents system swacting activity",
    epilog="Plugin file example:\n" "   algorithm=swact_activity\n",
)

# puppet errors algorithm
parser_puppet_errors = subparsers.add_parser(
    "puppet_errors",
    formatter_class=argparse.RawTextHelpFormatter,
    help="Presents any puppet errors",
    epilog="Plugin file example:\n" "   algorithm=puppet_errors\n",
)

# process failures algorithm
parser_process_failures = subparsers.add_parser(
    "process_failures",
    formatter_class=argparse.RawTextHelpFormatter,
    help="Presents any process failures from pmond.log",
    epilog="Plugin file example:\n" "   algorithm=process_failures\n",
)

# daemon failures algorithm
parser_daemon_failures = subparsers.add_parser(
    "daemon_failures",
    formatter_class=argparse.RawTextHelpFormatter,
    help="Presents any puppet manifest failures from daemon.log",
    epilog="Plugin file example:\n" "   algorithm=daemon_failures\n",
)

# heartbeat loss algorithm
parser_heartbeat_loss = subparsers.add_parser(
    "heartbeat_loss",
    formatter_class=argparse.RawTextHelpFormatter,
    help="Presents any heartbeat loss error messages from hbsAgent.log",
    epilog="Plugin file example:\n" "   algorithm=heartbeat_loss\n",
)

# maintenance errors algorithm
parser_maintenance_errors = subparsers.add_parser(
    "maintenance_errors",
    formatter_class=argparse.RawTextHelpFormatter,
    help="Presents errors and other relevant messages from mtcAgent.log and "
    "mtcClient.log",
    epilog="Plugin file example:\n" "   algorithm=maintenance_errors\n",
)

# state changes algorithm
parser_state_changes = subparsers.add_parser(
    "state_changes",
    formatter_class=argparse.RawTextHelpFormatter,
    help="Presents any messages from mtcAgent.log regarding the state of "
    "hosts, such as enabled/disabled",
    epilog="Plugin file example:\n" "   algorithm=state_changes\n",
)

# audit algorithm
parser_audit = subparsers.add_parser(
    "audit",
    formatter_class=argparse.RawTextHelpFormatter,
    help="Presents information about audit events in dcmanager.\n"
    "The rates and totals represents the sum of audits on all subclouds ",
    epilog="Plugin file example:\n"
    "   algorithm=audit\n"
    "   start=2022-06-01 10:00:00\n"
    "   end=2022-06-01 04:00:00\n",
)
parser_audit.add_argument(
    "--start",
    required=False,
    default=datetime.strftime(now - timedelta(days=7), "%Y-%m-%d %H:%M:%S"),
    type=str,
    help="Specify a start date in YYYY-MM-DD HH:MM:SS format for analysis "
    "(not required, default: 1 week ago)"
)
parser_audit.add_argument(
    "--end",
    required=False,
    default=datetime.strftime(now, "%Y-%m-%d %H:%M:%S"),
    type=str,
    help="Specify an end date in YYYY-MM-DD HH:MM:SS format for analysis "
    "(not required, default: today)"
)

args = parser.parse_args()
args.start = datetime.strptime(args.start, "%Y%m%d").strftime(
    "%Y-%m-%dT%H:%M:%S")
args.end = datetime.strptime(args.end, "%Y%m%d").strftime("%Y-%m-%dT%H:%M:%S")

###########################################################
#                 Args error checking
###########################################################
if args.file:
    if not os.path.exists(args.file):
        exit_msg = "Error: Specified file (" + args.file + ") does not exist."
        sys.exit(exit_msg)
    elif os.path.isdir(args.file):
        exit_msg = "Error: Specified file (" + args.file + ") is a directory."
        exit_msg += "\nPlease specify the full path to a tar file when using "
        exit_msg += "the --file option.\nOtherwise, use the --directory option"
        exit_msg += " instead."
        sys.exit(exit_msg)
    elif not tarfile.is_tarfile(args.file):
        exit_msg = "Error: Specified file (" + args.file + ") is not a tar "
        exit_msg += "file.\nPlease specify a tar file using the --file option."
        sys.exit(exit_msg)
    else:
        try:
            input_dir = os.path.dirname(args.file)
            output_dir = os.path.join(input_dir, analysis_folder_name)
            subprocess.run(["tar", "xfC", args.file], check=True)
        except subprocess.CalledProcessError as e:
            print(e)
        except PermissionError as e:
            print(e)
            sys.exit("Permission Error: Unable to extract bundle")


elif args.directory:
    # Get the bundle input and report output dirs
    output_dir = os.path.join(args.directory, analysis_folder_name)
    input_dir = os.path.join(args.directory)
    if not os.path.isdir(input_dir):
        sys.exit("Error: Specified input directory is not a directory")
elif args.bundle:
    output_dir = os.path.join(args.bundle, analysis_folder_name)
    input_dir = os.path.join(args.bundle)
else:
    exit_msg = "Error: Please use either the --file or --directory option to "
    exit_msg += "specify a\ncollect bundle file or directory containing a "
    exit_msg += "collect bundle file to analyze."
    sys.exit(exit_msg)


###########################################################
#                  Setup logging
###########################################################
logger = logging.getLogger()


def remove_logging():
    """Move logging to a different location ; from /tmp to the bundle"""

    logger = logging.getLogger()
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)


def setup_logging(logfile):
    """Setup logging"""

    # setting up logger
    formatter = logging.Formatter("%(message)s")

    logging.basicConfig(
        filename=logfile,
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
    )
    logging.Formatter.converter = time.gmtime

    console_handler = logging.StreamHandler()
    if args.debug:
        console_handler.setLevel(logging.DEBUG)
    else:
        console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)


setup_logging(tmp_report_log[1])

if args.debug:
    logger.debug("Arguments : %s", args)
    logger.debug("Report Dir: %s", report_dir)
    logger.debug("Input  Dir: %s", input_dir)
    logger.debug("Output Dir: %s", output_dir)

###########################################################
#        Find and extract the bundle to analyze
###########################################################


# List of directories to ignore
ignore_list = [analysis_folder_name]
ignore_list += ["apps", "horizon", "lighttpd", "lost+found", "sysinv-tmpdir"]
ignore_list += ["patch-api-proxy-tmpdir", "platform-api-proxy-tmpdir"]
regex_get_bundle_date = r".*_\d{8}\.\d{6}$"


class BundleObject:
    def __init__(self, input_dir):
        self.input_base_dir = input_dir  # the first specified input dir
        self.input_dir = input_dir       # current input_dir ; can change
        self.tar_file_found = False      # True if <bundle>.tar file present
        self.subcloud_bundle = False     # host vs subcloud bundle
        self.bundle_name = None          # full path of current bundle
        self.bundle_names = []           # list of bundle names
        self.bundle_info = ["", []]      # tarfile bundle info [name,[files]]
        self.bundles = []                # list of bundles
        self.tars = 0                    # number of tar files found
        self.tgzs = 0                    # number of host tgz files found
        self.plugins = []

    def debug_state(self, func):
        if args.state:
            logger.debug("State:%10s: input_base_dir : %s",
                         func, self.input_base_dir)
            logger.debug("State:%10s: input_dir      : %s",
                         func, self.input_dir)
            logger.debug("State:%10s: output_dir     : %s",
                         func, output_dir)
            logger.debug("State:%10s: tar_file_found : %s",
                         func, self.tar_file_found)
            logger.debug("State:%10s: subcloud_bundle: %s",
                         func, self.subcloud_bundle)
            logger.debug("State:%10s: bundle_name    : %s",
                         func, self.bundle_name)
            logger.debug("State:%10s: bundle_names   : %s",
                         func, self.bundle_names)
            logger.debug("State:%10s: bundle_info    : %s",
                         func, self.bundle_info)
            logger.debug("State:%10s: bundles        : %s",
                         func, self.bundles)
            logger.debug("State:%10s: tars-n-tgzs    : %s:%s",
                         func, self.tars, self.tgzs)

    def update_io_dirs(self, new_dir):
        """Update the input_dir and output_dir dirs

        Parameters:
           new_dir (string): path to change input_dir to
        """
        self.debug_state("get_bundles")
        global output_dir
        if self.input_dir != new_dir:
            str1 = "input_dir change: " + self.input_dir + " -> " + new_dir
            self.input_dir = new_dir
            old_output_dir = output_dir
            output_dir = os.path.join(self.input_dir, analysis_folder_name)
            str2 = "output_dir change: " + old_output_dir + " -> " + output_dir
        else:
            str1 = "input_dir  change is null"
            str2 = "output_dir change is null"
        logger.debug(str1)
        logger.debug(str2)
        self.debug_state("update_io_dirs")

    def get_bundles(self):
        """Get a list of all collect bundle from input_dir"""

        self.debug_state("get_bundles")
        logger.debug("get_bundles: %s", self.input_dir)
        for obj in (os.scandir(self.input_dir)):
            # Don't display dirs from the ignore list.
            # This makes the bundle selection list cleaner when
            # report is run against /scratch
            ignored = False
            for ignore in ignore_list:
                if obj.name == ignore:
                    ignored = True
                    break
            if ignored is True:
                continue

            if obj.is_dir(follow_symlinks=False):
                date_time = obj.name[-15:]
                if args.debug:
                    logger.debug("found dir : %s : %s", obj.name, date_time)
            elif os.path.islink(obj.path):
                # ignore sym links
                continue
            else:
                if not tarfile.is_tarfile(obj.path):
                    continue
                filename = os.path.splitext(obj.name)[0]
                date_time = filename[-15:]
                if args.debug:
                    logger.debug("found file: %s : %s", obj.name, date_time)

            # Add this bundle to the list. Avoid duplicates
            found = False
            name = obj.name
            if obj.name.endswith('.tar'):
                self.tar_file_found = True
                name = os.path.splitext(obj.name)[0]
            if obj.name.endswith('.tgz'):
                continue
            for bundle in self.bundles:
                if bundle == name:
                    found = True
                    break
            if found is False:
                if re.match(regex_get_bundle_date, name):
                    self.bundles.append(name)
                    self.bundle_names.append(name)
                elif not obj.is_dir(follow_symlinks=False):
                    logger.info("unexpected bundle name '%s'", name)
                    logger.info("... collect bundles name should include "
                                "'_YYYYMMDD.HHMMSS'")
                    select = str(input('accept as bundle (Y/N): '))
                    if select[0] == 'Y' or select[0] == 'y':
                        self.bundles.append(name)
                        self.bundle_names.append(name)
                    else:
                        logger.warning("not a bundle")

        if args.debug:
            logger.debug("bundles %2d: %s", len(self.bundles), self.bundles)
            logger.debug("bundle sel: %s", self.bundle_names)
        self.debug_state("get_bundles")

    def get_bundle(self):
        """Get a list of all collect bundles from input_dir

        Parameters:
            input_dir (string): path to the directory to analyze
        """
        self.debug_state("get_bundle")
        logger.debug("get_bundle %s", self.input_dir)

        if self.tar_file_found is False:
            # If a collect bundle .tar file is not found then treat this
            # case as though the input_dir is a hosts tarball directory
            # like would be seen when running report on the system during
            # the collect operation.
            logger.debug("get_bundle tar file not found")
            self.bundle_name = self.input_dir

        elif len(self.bundles) > 1:
            retry = True
            while retry is True:
                logger.info("0 - exit")
                idx = 1
                for bundle in self.bundle_names:
                    if bundle.endswith(('.tar', '.tgz', '.gz')):
                        logger.info("%d - %s",
                                    idx, os.path.splitext(bundle)[0])
                    else:
                        logger.info("%d - %s", idx, bundle)
                    idx += 1
                try:
                    select = int(input('Please select bundle to analyze: '))
                except ValueError:
                    logger.info("Invalid input; integer between 1 "
                                "and %d required", len(self.bundles))
                    continue
                if not select:
                    sys.exit()
                if select <= len(self.bundles):
                    idx = 0
                    for bundle in self.bundle_names:
                        if idx == select-1:
                            logger.info("%s selected", bundle)
                            self.bundle_name = bundle
                            break
                        else:
                            idx += 1
                    retry = False
                else:
                    logger.info("Invalid selection (%s) idx=%d",
                                select, idx)
        # single bundle found
        else:
            self.bundle_name = self.bundle_names[0]
            logger.debug("bundle name: %s", self.bundle_name)
        self.debug_state("get_bundle")

    def get_bundle_info(self, bundle):
        """Returns a list containing the tar file content

           This is required for cases where the name of the supplied
           tar file extracts its contents to a directory that is not
           the same (without the extension) as the original tar file

        Returns:
           bundle_info (list): the bundle info [ "dir", [ files ]]
           bundle_info[0] ( string) 'directory' found in tar file
           bundle_info[1] (list) a list of files found in 'directory'
        """
        self.debug_state("get_bundle_info")

        bundle_tar = os.path.join(self.input_dir, self.bundle_name) + ".tar"
        logger.debug("get_bundle_info %s", bundle_tar)

        if not os.path.exists(bundle_tar):
            logger.error("Error: No collect tar bundle found: %s", bundle_tar)
            sys.exit()
        try:
            result = subprocess.run(["tar", "tf", bundle_tar],
                                    stdout=subprocess.PIPE)
            output = result.stdout.decode('utf-8').splitlines()
            logger.debug("... bundle info: %s", output)
        except subprocess.CalledProcessError as e:
            logger.error(e)
        except subprocess.PermissionError as e:
            logger.error(e)

        if output != []:
            for item in output:
                dir, file = item.split("/", 1)
                if dir is None:
                    continue
                if self.bundle_info[0] == "":
                    self.bundle_info[0] = dir
                if self.bundle_info[0] != dir:
                    logger.warning("ignoring unexpected extra directory "
                                   "only one directory permitted in a "
                                   "collect bundle ; %s is != %s",
                                   self.bundle_info[0], dir)
                    continue
                elif file.endswith(('.tar')):
                    logger.debug("tar contains tar: %s", file)
                    self.bundle_info[1].append(file)
                elif file.endswith(('.tgz')):
                    logger.debug("tar contains tgz: %s", file)
                    if self.bundle_info[0] is None:
                        self.bundle_info[0] = dir
                    self.bundle_info[1].append(file)
                else:
                    if self.bundle_info[0] is None:
                        self.bundle_info[0] = dir
                    if file:
                        self.bundle_info[1].append(file)
        self.debug_state("get_bundle_info")

    def extract_bundle(self):
        """Extract bundle if not already extracted"""

        logger.debug("bundle name: %s", self.bundle_name)

        # extract the bundle if not already extracted
        bundle_tar = os.path.join(self.input_dir, self.bundle_name) + ".tar"
        if os.path.exists(bundle_tar):
            if not os.access(self.input_dir, os.W_OK):
                logger.error("Permission Error: Bundle dir not writable: %s",
                             self.input_dir)
                sys.exit("Collect bundle must be writable for analysis.")
            try:

                logger.info("extracting %s", bundle_tar)
                untar_data = subprocess.run(
                    ["tar", "xfC", bundle_tar, self.input_dir],
                    check=True, stdout=subprocess.PIPE)
                logger.debug(untar_data)
            except subprocess.CalledProcessError as e:
                logger.error(e)
            except PermissionError as e:
                logger.error(e)
                sys.exit("Permission Error: Unable to extract bundle")

        elif args.debug:
            logger.debug("already extracted: %s", bundle_tar)

    def get_bundle_type(self):
        """Determine the bundle type ; host or subcloud

           Subcloud bundles contain one or more tar files rather
           than tgz files ; at this level.

           However rather than fail the report if both are found,
           which is unlikely, the code favors treating as a normal
           host bundle with the tgz check first.
        """
        if self.tgzs:
            self.extract_bundle()
            self.bundle_name = os.path.join(self.input_dir,
                                            self.bundle_info[0])
            logger.debug("Host bundle: %s", self.bundle_name)
        elif self.tars:
            self.extract_bundle()
            self.bundle_name = os.path.join(self.input_dir,
                                            self.bundle_info[0])
            self.subcloud_bundle = True
            logger.debug("Subcloud bundle: %s", self.bundle_name)
        else:
            sys.exit("Error: bundle contains no .tar files")

        self.update_io_dirs(self.bundle_name)
        if self.subcloud_bundle is True:
            # clear current bundle lists, etc. in prep for the
            # selected subcloud bundle
            self.bundle_names = []
            self.bundles = []
            self.bundle_name = None
            self.tar_file_found = False

            # get the subcloud bundle(s) and select one
            # if more than one is present.
            self.get_bundles()
            if self.bundles:
                self.get_bundle()

            # handle the no bundles found case ; unlikely
            if self.bundle_name is None:
                sys.exit("No valid collect subcloud bundles found.")

            # extract the subcloud bundle if needed
            self.extract_bundle()

            # add the full path to the bundle name.
            # can't use self.bundle_info[0] because that is the
            # bundle name that contians the subcloud tars
            self.bundle_name = os.path.join(self.input_dir, self.bundle_name)

            # update the input directory to point top the subcloud folder
            self.update_io_dirs(self.bundle_name)

        self.debug_state("get_bundle_type")

    def load_plugin(self, path_plugin=None):
        """Load a single plugin from the specified path location

        Parameters:

           path_plugin: string
              The full path and file name of the plugin to load
        """
        if path_plugin is not None:
            # redundant check but more robust
            if os.path.exists(path_plugin):
                logger.debug("adding plugin: %s", path_plugin)
                self.plugins.append(Plugin(path_plugin))
            else:
                logger.warning("Warning: plugin '%s' not found", path_plugin)
        else:
            logger.warning("Warning: load_plugin failed ; no plugin specified")

    def load_plugins(self, path=None):
        """Load plugins from the specified path location

        Parameters:

           path: string
              The path to the directory of where to load plugins
        """
        if path is not None and os.path.exists(path):
            for plugin in os.listdir(path):
                path_plugin = os.path.join(path, plugin)

                # skip over empty files like __init__.py
                if os.path.getsize(path_plugin) == 0:
                    logger.debug("skipping empty plugin '%s'", plugin)
                    continue

                logger.debug("adding plugin: %s/%s", path, plugin)
                self.plugins.append(Plugin(path_plugin))

        else:
            logger.warning("unable to load plugins from %s ; "
                           "path does not exist", path)


# Initialize the Bundle Object. Logging starts in /tmp
obj = BundleObject(input_dir)
with open(os.path.join(output_dir, tmp_report_log[1]), "a") as logfile:

    obj.debug_state("init")

    if args.bundle:
        logger.info("Bundle: %s", args.bundle)
        obj.input_dir = input_dir

    elif args.file:
        # Note: The args.file has already been validated at this point.
        basename = os.path.splitext(os.path.basename(args.file))
        if re.match(regex_get_bundle_date, basename[0]):
            obj.bundles.append(basename[0])
            obj.bundle_names.append(basename[0])
            obj.tar_file_found = True
        else:
            logger.info("unexpected bundle name '%s'", basename[0])
            logger.info("... collect bundles name should include "
                        "'_YYYYMMDD.HHMMSS'")
            select = str(input('accept as bundle (Y/N): '))
            if select[0] == 'Y' or select[0] == 'y':
                obj.bundles.append(basename[0])
                obj.bundle_names.append(basename[0])
                obj.tar_file_found = True
            else:
                sys.exit("rejected ; exiting ...")
    else:
        # get the bundles
        obj.get_bundles()

    if not args.bundle:
        if obj.bundles:
            obj.get_bundle()

        # handle the no bundles found case
        if obj.bundle_name is None:
            sys.exit("No valid collect host bundles found.")

        obj.get_bundle_info(obj.bundle_name)
        logger.debug("bundle info: %s", obj.bundle_info)
        for file in obj.bundle_info[1]:
            if file.endswith(('.tar')):
                logger.debug("bundle tar file: %s", file)
                obj.tars += 1
            elif file.endswith(('.tgz')):
                logger.debug("bundle tgz file: %s", file)
                obj.tgzs += 1

if not args.bundle:
    obj.get_bundle_type()

# now that the output directory is established create the analysis
# folder, move the existing log files there and record the untar data
if not os.path.exists(output_dir):
    try:
        result = os.makedirs(output_dir, exist_ok=True)
    except PermissionError as e:
        logger.error(e)
        sys.exit("Permission Error: Unable to create report")

# remove the pluin data if it already exists
plugin_data_output_dir = os.path.join(output_dir, "plugins")
if os.path.exists(plugin_data_output_dir):
    logger.debug("cleaning up old plugin data: %s", plugin_data_output_dir)
    shutil.rmtree(plugin_data_output_dir)

# relocate logging to the selected bundle directory
remove_logging()
new_log_file = output_dir + "/report.log"
shutil.move(tmp_report_log[1], new_log_file)
setup_logging(new_log_file)

logger.info("")
logger.info("Report: %s ", output_dir)
logger.info("")

# initialize the execution engine
try:
    engine = ExecutionEngine(args, obj.input_dir, output_dir)
except ValueError as e:
    logger.error(str(e))
    logger.error("Confirm you are running the report tool on a collect bundle")

# Get the full path to the possible plugin dirs
builtin_plugins_path = os.path.join(report_dir, "plugins")
localhost_plugins_path = os.path.join("/etc/collect", "plugins")

logger.debug("vars(args)    : %s", vars(args))
logger.debug("args.algorithm: %s", args.algorithm)
logger.debug("args.plugin   : %s", args.plugin)
logger.debug("obj.plugins   : %s", obj.plugins)

if args.algorithm:
    plugins.append(Plugin(opts=vars(args)))
elif args.plugin:
    logger.debug("plugin option specified")
    system_info_plugin_added = False
    for p in args.plugin:
        logger.debug("searching for plugin '%s'", p)

        # look for the plugin
        if os.path.exists(os.path.join(builtin_plugins_path, p)):
            obj.load_plugin(os.path.join(builtin_plugins_path, p))
        elif os.path.exists(os.path.join(localhost_plugins_path, p)):
            obj.load_plugin(os.path.join(localhost_plugins_path, p))
        else:
            logger.warning("Warning: specified plugin '%s' not found", p)

        if p == algorithms.SYSTEM_INFO:
            system_info_plugin_added = True
    if not system_info_plugin_added:
        obj.load_plugin(os.path.join(
            builtin_plugins_path, algorithms.SYSTEM_INFO))

else:
    # load builtin plugins
    obj.load_plugins(builtin_plugins_path)

    # add localhost plugins
    obj.load_plugins(localhost_plugins_path)


# analyze the collect bundle
engine.execute(obj.plugins, output_dir)

# generate report tool rendering html file
render.main(input_dir, output_dir)

sys.exit()
