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
# The report tool reads user plugins from a plugins directory in the
# top level of the collect bundle, and outputs files containing
# relevant logs to a report directory in the top level as well.
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
from datetime import timezone
import logging
import os
import time

from execution_engine import ExecutionEngine
from plugin import Plugin


now = datetime.now(timezone.utc)
base_dir = os.path.realpath(__file__)
default_path = os.path.join(os.path.dirname(base_dir), "..", "..")
plugins = []

parser = argparse.ArgumentParser(
    description="Log Event Reporter",
    epilog="Place plugins in 'plugins' directory at top level of collect bundle. Output files will be placed in 'report' directory."
    "\nThis tool will create a report.log file along with other output files",
)
parser.add_argument(
    "-s",
    "--start",
    default="20000101",
    help="Specify a start date in YYYYMMDD format for analysis (default:20000101)",
)
parser.add_argument(
    "-e",
    "--end",
    default=datetime.strftime(now, "%Y%m%d"),
    help="Specify an end date in YYYYMMDD format for analysis (default: current date)",
)
parser.add_argument(
    "-p",
    "--plugin",
    default=None,
    nargs="*",
    help="Specify what plugins to run (default: runs every plugin in plugins folder)",
)
parser.add_argument(
    "-d",
    "--directory",
    default=default_path,
    help="Specify top level of collect bundle to analyze (default: two levels above current location)",
)
subparsers = parser.add_subparsers(help="algorithms", dest="algorithm")

# substring algorithm arguments
parser_substring = subparsers.add_parser(
    "substring",
    formatter_class=argparse.RawTextHelpFormatter,
    help="""Searches through specified files for lines containing specified substring.
            There will be an output file for each host of the host type specified.""",
    epilog="Plugin file example:\n"
    "   algorithm=substring\n"
    "   files=mtcAgent.log, sm.log\n"
    "   hosts=controllers, workers\n"
    "   substring=Swact in progress\n"
    "   substring=Swact update",
)
substring_required = parser_substring.add_argument_group("required arguments")
substring_required.add_argument(
    "--files",
    required=True,
    nargs="+",
    help="Files to perform substring analysis on (required)",
)
substring_required.add_argument(
    "--substring", nargs="+", required=True, help="Substrings to search for (required)"
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
    help="Searches through fm.db.sql.txt for alarms and logs. There are 2 output files: 'alarm', and 'log'",
    epilog="Plugin file example:\n"
    "   algorithm=alarm\n"
    "   alarm_ids=400.005,200.004\n"
    "   entity_ids= host=controller-0,host=controller-1\n",
)
parser_alarm.add_argument(
    "--alarm_ids",
    nargs="+",
    required=False,
    default=[],
    help="Alarm id patterns to search for (not required)",
)
parser_alarm.add_argument(
    "--entity_ids",
    nargs="+",
    required=False,
    default=[],
    help="Entity id patterns to search for (not required)",
)

# system info algorithm
parser_system_info = subparsers.add_parser(
    "system_info",
    formatter_class=argparse.RawTextHelpFormatter,
    help="Presents information about the system",
    epilog="Plugin file example:\n" "   algorithm=system_info\n",
)

# swact activity algorithm
parser_swact = subparsers.add_parser(
    "swact",
    formatter_class=argparse.RawTextHelpFormatter,
    help="Presents system swacting activity",
    epilog="Plugin file example:\n" "   algorithm=swact\n",
)

# puppet errors algorithm
parser_puppet = subparsers.add_parser(
    "puppet",
    formatter_class=argparse.RawTextHelpFormatter,
    help="Presents any puppet errors",
    epilog="Plugin file example:\n" "   algorithm=puppet\n",
)

# process failure algorithm
parser_process_failure = subparsers.add_parser(
    "process_failure",
    formatter_class=argparse.RawTextHelpFormatter,
    help="Presents any process failures from pmond.log",
    epilog="Plugin file example:\n" "   algorithm=process_failure\n",
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
parser_audit_required = parser_audit.add_argument_group("required arguments")
parser_audit_required.add_argument("--start", required=True)
parser_audit_required.add_argument(
    "--end",
    required=True,
)


args = parser.parse_args()
args.start = datetime.strptime(args.start, "%Y%m%d").strftime("%Y-%m-%dT%H:%M:%S")
args.end = datetime.strptime(args.end, "%Y%m%d").strftime("%Y-%m-%dT%H:%M:%S")

output_directory = os.path.join(
    args.directory, "report", "output", now.strftime("%Y%m%d.%H%M%S")
)

# creating report log
os.makedirs(output_directory)
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

try:
    engine = ExecutionEngine(args)
except ValueError as e:
    logger.error(str(e))

if args.algorithm:
    plugins.append(Plugin(opts=vars(args)))
else:
    if args.plugin:
        for p in args.plugin:
            path = os.path.join(args.directory, "plugins", p)
            if os.path.exists(path):
                try:
                    plugins.append(Plugin(path))
                except Exception as e:
                    logger.error(str(e))

            else:
                logger.warning(f"{p} plugin does not exist")
    else:
        path = os.path.join(args.directory, "plugins")
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
