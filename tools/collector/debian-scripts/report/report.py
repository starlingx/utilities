#!/usr/bin/env python3
########################################################################
#
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# Description: The Report tool is used to gather relevant log events
#              and information about the system from a collect bundle.
#
# The report tool allows user created plugins which decides relevance
# for log events. Plugins contain an algorithm label which instructs the
# tool what information to search and how to search for it.
#
# The report tool requires the collect bundle and host tarballs to be
# untarred.
#
# The report tool reads user plugins from the report directory in the
# top level of the collect bundle, and outputs files containing files
# containing relevant logs to this directory as well.
#
# Typical Usage:
#  command line                      functionality
#  -------------------------------   ----------------------------------
# > report.py                        - Run all plugins in directory
# > report.py [plugin ...]           - Run only specified plugins
# > report.py <algorithm> [labels]   - Run algorithm with labels
# > report.py --help                 - help message
# > report.py <algorithm> --help     - algorithm specific help
#
#    See --help output for a complete list of full and abbreviated
#    command line options and examples of plugins.
#
# Refer to README file for more usage and output examples
#######################################################################

import argparse
from cmath import log
from datetime import datetime
from datetime import timedelta
from datetime import timezone
import logging
import os
import subprocess
import sys
import time

from execution_engine import ExecutionEngine
from plugin import Plugin


now = datetime.now(timezone.utc)
base_dir = os.path.dirname(os.path.realpath(__file__))
parent_dir = os.path.dirname(base_dir)
default_path = os.path.dirname(parent_dir)
plugins = []

parser = argparse.ArgumentParser(
    description="Log Event Reporter",
    epilog="Place plugins in 'plugins' directory found in 'report' directory "
    "at top level of collect bundle.\nOutput files will be placed in 'report' "
    "directory.\nThis tool will create a report.log and untar.log file along "
    "with other output files.",
)
parser.add_argument(
    "-v",
    "--verbose",
    action="store_true",
    help="Verbose output",
)
parser.add_argument(
    "-s",
    "--start",
    default="20000101",
    help="Specify a start date in YYYYMMDD format for analysis "
    "(default:20000101)",
)
parser.add_argument(
    "-e",
    "--end",
    default=datetime.strftime(now + timedelta(days=1), "%Y%m%d"),
    help="Specify an end date in YYYYMMDD format for analysis "
    "(default: current date)",
)
parser.add_argument(
    "-p",
    "--plugin",
    default=None,
    nargs="*",
    help="Specify what plugins to run (default: runs every plugin in plugins "
    "folder)",
)
parser.add_argument(
    "-d",
    "--directory",
    default=default_path,
    help="Specify top level of collect bundle to analyze "
    "(default: two levels above tool directory)",
)
parser.add_argument(
    "--hostname",
    default="all",
    help="Specify host for correlator to find significant events and state "
    "changes for (default: all hosts)",
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

if args.directory.endswith("/"):
    output_directory = os.path.join(
        default_path, "report", "output",
        os.path.basename(os.path.dirname(args.directory))
    )
else:
    output_directory = os.path.join(
        default_path, "report", "output", os.path.basename(args.directory)
    )

# creating report log
os.makedirs(output_directory, exist_ok=True)
open(os.path.join(output_directory, "report.log"), "w").close()

# setting up logger
formatter = logging.Formatter("%(message)s")
logger = logging.getLogger()

logging.basicConfig(
    filename=os.path.join(output_directory, "report.log"),
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logging.Formatter.converter = time.gmtime

ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
ch.setFormatter(formatter)

logger.addHandler(ch)

if not os.path.isdir(args.directory):
    sys.exit("Top level of collect bundle given to analyze is not a directory")
else:
    for obj in (os.scandir(args.directory)):
        info = os.path.splitext(obj.name)

        # TODO: ask user which file to report on if more than one tarball in
        #       directory
        # Check if collect tarball is in given directory and extracts it if
        # not already done
        if (obj.is_file() and info[1] == ".tar"):
            try:
                result = subprocess.check_output(["tar", "tf", obj.path],
                                                 encoding="UTF-8")
                result = result.split("\n", 1)
                if not os.path.isdir(os.path.join(args.directory,
                                                  os.path.dirname(result[0]))):
                    subprocess.run(["tar", "xfC", obj.path, args.directory],
                                   check=True)
                    subprocess.run(["echo", "extracted", obj.name], check=True)
                args.directory = os.path.join(args.directory,
                                              os.path.dirname(result[0]))
                break
            except subprocess.CalledProcessError as e:
                logger.error(e)

try:
    engine = ExecutionEngine(args, output_directory)
except ValueError as e:
    logger.error(str(e))
    sys.exit("Confirm you are running the report tool on a collect bundle")

if args.algorithm:
    plugins.append(Plugin(opts=vars(args)))
else:
    if args.plugin:
        for p in args.plugin:
            path = os.path.join(default_path, "report", "plugins", p)
            if os.path.exists(path):
                try:
                    plugins.append(Plugin(path))
                except Exception as e:
                    logger.error(str(e))

            else:
                logger.warning(f"{p} plugin does not exist")
    else:
        path = os.path.join(default_path, "report", "plugins")
        if not os.path.exists(path):
            os.mkdir(path)
            logger.error("Plugins folder is empty")
        else:
            for file in os.listdir(path):
                try:
                    plugins.append(Plugin(os.path.join(path, file)))
                except Exception as e:
                    logger.error(str(e))

engine.execute(plugins, output_directory)
