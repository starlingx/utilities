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
# > report.py -d <collect bundle dir> - Run all plugins against bundle
# > report.py -d <dir> [plugin ...]   - Run only specified plugins
# > report.py -d <dir> <algs> [labels]- Run algorithm with labels
# > report.py <algorithm> --help      - algorithm specific help
#
#    See --help output for a complete list of full and abbreviated
#    command line options and examples of plugins.
#
# TODO: revise README
# Refer to README file for more usage and output examples
#######################################################################

import argparse
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import logging
import os
import shutil
import subprocess
import sys
import tarfile
import time

from execution_engine import ExecutionEngine
from plugin import Plugin

now = datetime.now(timezone.utc)
report_dir = os.path.dirname(os.path.realpath(__file__))
analysis_folder_name = "report_analysis"
bundle_name = None
plugins = []

clean = True

# TODO: rework this description
parser = argparse.ArgumentParser(
    description="Log Event Reporter",
    epilog="Analyzes data collected by the plugins and produces a "
    "report_analysis stored with the collect bundle. The report tool "
    "can be run either on or off system by specifying the bundle to "
    "analyze using the --directory or -d <directory> command option.",
)

parser.add_argument(
    "--debug",
    action="store_true",
    help="Enable debug logs",
)

parser.add_argument(
    "--clean", "-c",
    action="store_true",
    help="Cleanup (remove) existing report data",
)

parser.add_argument(
    "--directory", "-d",
    default="",
    required=False,
    help="Specify the full path to a directory containing a collect "
    "bundle to analyze. This is a required parameter",
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
    help="Specify host for correlator to find significant events and "
    "state changes for (default: all hosts)",
)

parser.add_argument(
    "--plugin", "-p",
    default=None,
    nargs="*",
    help="Specify comma separated list of plugins to run "
    "(default: runs all found plugins)",
)

parser.add_argument(
    "--start", "-s",
    default="20000101",
    help="Specify a start date in YYYYMMDD format for analysis "
    "(default:20000101)",
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
            input_dir = os.path.splitext(args.file)[0]
            input_file = os.path.dirname(os.path.realpath(args.file))
            output_dir = os.path.join(input_dir, analysis_folder_name)
            # print("input_file : ", input_file)
            subprocess.run(["tar", "xfC", args.file, input_file], check=True)
            # print("extracted ", args.file)
        except subprocess.CalledProcessError as e:
            print(e)

elif args.directory:
    # Get the bundle input and report output dirs
    output_dir = os.path.join(args.directory, analysis_folder_name)
    input_dir = os.path.join(args.directory)
else:
    exit_msg = "Error: Please use either the --file or --directory option to "
    exit_msg += "specify a\ncollect bundle file or directory containing a "
    exit_msg += "collect bundle file to analyze."
    sys.exit(exit_msg)

# TODO: date current analysis if there rather than remove
if args.clean and not clean:
    clean = True
if clean is True and os.path.exists(output_dir):
    shutil.rmtree(output_dir)
os.makedirs(output_dir, exist_ok=True)

# setting up logger
formatter = logging.Formatter("%(message)s")
logger = logging.getLogger()

logging.basicConfig(
    filename=os.path.join(output_dir, "report.log"),
    level=logging.DEBUG,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logging.Formatter.converter = time.gmtime

ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
if args.debug:
    ch.setLevel(logging.DEBUG)
ch.setFormatter(formatter)

logger.addHandler(ch)

# Command line parsing done. Logging setup

#####################################################################
#             Find and extract the bundle to analyze
#####################################################################
# Find and extract the bundle to analyze

# Creating report log
open(os.path.join(output_dir, "report.log"), "w").close()

if args.debug:
    logger.debug("Arguments : %s", args)
    logger.debug("Report Dir: %s", report_dir)
    logger.debug("Input  Dir: %s", input_dir)
    logger.debug("Output Dir: %s", output_dir)

if not os.path.isdir(input_dir):
    sys.exit("Error: Specified input directory is not a directory")

# Search 'input_dir' for bundles.
bundle_tar_file_found = False
bundle_name = None
bundle_names = []
bundles = []
ignore_list = [analysis_folder_name]
ignore_list += ["apps", "horizon", "lighttpd", "lost+found", "sysinv-tmpdir"]

with open(os.path.join(output_dir, "untar.log"), "a") as logfile:
    for obj in (os.scandir(input_dir)):
        # Don't display dirs from the ignore list.
        # This makes the bundle selection list cleaner when
        # report is run against /scratch
        ignored = False
        for ignore in ignore_list:
            if obj.name == ignore:
                ignored = True
        if ignored is True:
            continue

        if obj.is_dir(follow_symlinks=False):
            date_time = obj.name[-15:]
            if args.debug:
                logger.debug("Found Dir : %s : %s", obj.name, date_time)
        else:
            if not tarfile.is_tarfile(obj.path):
                continue
            filename = os.path.splitext(obj.name)[0]
            date_time = filename[-15:]
            if args.debug:
                logger.debug("Found File: %s : %s", obj.name, date_time)

        # TODO: Add more filtering above to avoid directories that are
        #       clearly not collect data is not added to the list of
        #       options.

        # Add this bundle to the list. Avoid duplicates
        found = False
        name = obj.name
        if obj.name.endswith('.tar'):
            bundle_tar_file_found = True
            name = os.path.splitext(obj.name)[0]
        for bundle in bundles:
            if bundle == name:
                found = True
                break
        if found is False:
            bundles.append(name)
            bundle_names.append(name)
        else:
            logger.debug("Discarding duplicate %s", obj.name)

if args.debug:
    logger.debug("Bundle  %d : %s", len(bundles), bundles)
    logger.debug("Bundle Sel: %s", bundle_names)

if bundles:
    if bundle_tar_file_found is False:
        # If a collect bundle .tar file is not found then treat this
        # case as though the input_dir is a hosts tarball directory
        # like would be seen when running report on the system during
        # the collect operation.
        bundle_name = input_dir

    elif len(bundles) > 1:
        retry = True
        while retry is True:
            logger.info("0 - exit")
            index = 1
            # TODO: filter files/dirs with date.time ; 20221102.143258
            for bundle in bundle_names:
                if bundle.endswith(('.tar', '.tgz', '.gz')):
                    logger.info("%d - %s", index, os.path.splitext(bundle)[0])
                else:
                    logger.info("%d - %s", index, bundle)
                index += 1
            try:
                select = int(input('Please select the bundle to analyze: '))
            except ValueError:
                logger.info("Invalid input; integer between 1 "
                            "and %d required", len(bundles))
                continue
            if not select:
                sys.exit()
            if select <= len(bundles):
                index = 0
                for bundle in bundle_names:
                    if index == select-1:
                        logger.info("%s selected", bundle)
                        bundle_name = bundle
                        break
                    else:
                        index += 1
                retry = False
            else:
                logger.info("Invalid selection (%s) index=%d",
                            select, index)
    # single bundle found
    else:
        # logger.info("bundle_names: %s", bundle_names)
        bundle_name = bundle_names[0]

# handle the no bundles found case
if bundle_name is None:
    sys.exit("No valid collect bundles found.")

# extract the bundle if not already extracted
path_file = os.path.join(input_dir, bundle_name)
if not os.path.isdir(path_file):
    try:
        logger.info("extracting %s", path_file)
        subprocess.run(["tar", "xfC", path_file+".tar", input_dir], check=True)
    except subprocess.CalledProcessError as e:
        logger.error(e)

elif args.debug:
    logger.debug("already extracted ...")

# create the output directory ; report_analysis
output_dir = os.path.join(path_file, analysis_folder_name)
if not os.path.exists(output_dir):
    os.makedirs(output_dir, exist_ok=True)

# initialize the execution engine
try:
    engine = ExecutionEngine(args, path_file, output_dir)
except ValueError as e:
    logger.error(str(e))
    sys.exit("Confirm you are running the report tool on a collect bundle")

if args.algorithm:
    plugins.append(Plugin(opts=vars(args)))
elif args.plugin:
    for p in args.plugin:
        path = os.path.join(report_dir, "plugins", p)
        if os.path.exists(path):
            try:
                plugins.append(Plugin(path))
            except Exception as e:
                logger.error(str(e))

        else:
            logger.warning("%s plugin does not exist", p)
else:
    # load builtin plugins
    builtin_plugins = os.path.join(report_dir, "plugins")
    if os.path.exists(builtin_plugins):
        for file in os.listdir(builtin_plugins):
            plugins.append(Plugin(os.path.join(builtin_plugins, file)))
            logger.debug("loading built-in  plugin: %s", file)

    # add localhost plugins
    localhost_plugins = os.path.join("/etc/collect", "plugins")
    if os.path.exists(localhost_plugins):
        for file in os.listdir(localhost_plugins):
            plugins.append(Plugin(os.path.join(localhost_plugins, file)))
            logger.debug("loading localhost plugin: %s", file)

    # analyze the collect bundle
    engine.execute(plugins, output_dir)

sys.exit()
