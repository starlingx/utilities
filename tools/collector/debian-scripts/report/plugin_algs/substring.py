########################################################################
#
# Copyright (c) 2022 - 2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# This file contains the functions for the substring plugin algorithm.
#
# The substring plugin algorithm looks for a set of substrings within
# a list of log files and extracts those log messages.
#
########################################################################

from datetime import datetime
import gzip
import logging
import os
import re
import subprocess


logger = logging.getLogger(__name__)


def substring(start, end, substr, files, exclude_list=None, dropped_logs=None):
    """Substring algorithm
    Looks for all substrings in substr within files

    Parameters:
        start (string): Start time for analysis
        end (string): End time for analysis
        substr (string list): List of substrings to look for
        files  (string list): List of absolute filepaths to search in
        exclude_list (string list): list of strings to exclude from report
        dropped_logs (string): path/filename to write dropped logs
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
                else:
                    data.append("File not found: " + file)
                    continue
            cont = True
            # Searching through file
            command = (f"""grep -Ea "{'|'.join(s for s in substr)}" """
                       f"""{file} 2>/dev/null""")
            status = _continue(start, end, file)

            if (status == CONTINUE_CURRENT or
                    status == CONTINUE_CURRENT_OLD):
                # continue with current file
                if status == CONTINUE_CURRENT:
                    cont = False
                _evaluate_substring(start, end, data, command, dropped_logs)

            # Searching through rotated log files that aren't compressed
            n = 1
            while os.path.exists(f"{file}.{n}") and cont:
                command = (f"""grep -Ea "{'|'.join(s for s in substr)}" """
                           f"""{file}.{n} 2>/dev/null""")
                status = _continue(start, end, f"{file}.{n}")

                if (status == CONTINUE_CURRENT or
                        status == CONTINUE_CURRENT_OLD):
                    if status == CONTINUE_CURRENT:
                        cont = False
                    _evaluate_substring(start, end, data, command,
                                        dropped_logs)

                n += 1

            # Searching through rotated log files
            while os.path.exists(f"{file}.{n}.gz") and cont:
                command = (f"""zgrep -E "{'|'.join(s for s in substr)}" """
                           f"""{file}.{n}.gz 2>/dev/null""")
                status = _continue(start, end, f"{file}.{n}.gz",
                                   compressed=True)

                if (status == CONTINUE_CURRENT or
                        status == CONTINUE_CURRENT_OLD):
                    if status == CONTINUE_CURRENT:
                        cont = False
                    _evaluate_substring(start, end, data, command,
                                        dropped_logs)

                n += 1

        except FileNotFoundError as e:
            logger.error(e)
            continue

    # now remove any logs that contain substrings in the exclude_list
    if exclude_list:
        filtered_data = []
        for e in data:
            found = False
            for exclude in exclude_list:
                if e.find(exclude) != -1:
                    found = True
            if found is False:
                filtered_data.append(e)
        return sorted(filtered_data)
    return sorted(data)


def _continue(start, end, file, compressed=False):
    """Determines if substring algorithm should analyze the current file
    and older files based on if the time of the first log message in file
    is less than or greater than end and less than or greater than start

    Parameters:
        start (string): Start time for analysis
        end (string): End time for analysis
        file  (string): Current file
        compressed (boolean): Indicates if current file is compressed or not
    """
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

    if first < start:
        return CONTINUE_CURRENT
    elif first < end and first > start:
        return CONTINUE_CURRENT_OLD
    elif first > end:
        return CONTINUE_OLD


def _evaluate_substring(start, end, data, command, dropped_logs=None):
    """Adds log messages from output from running command to data if the
    timestamp of log message in greater than start and less than end

    Parameters:
        start (string): Start time for analysis
        end (string): End time for analysis
        data (string list): Log messages extracted so far
        command (string): Shell command to run
        dropped_logs (string): full path/filename of the file to record
                               logs that have been dropped due to bad format.
    """
    p = subprocess.Popen(command, shell=True, stdout=subprocess.PIPE)
    for raw_line in p.stdout:
        try:
            line = raw_line.decode("utf-8")
        except UnicodeDecodeError:
            if dropped_logs is not None:
                with open(dropped_logs, 'ab') as file:
                    file.write(raw_line)
            continue

        # different date locations for log events
        dates = [line[0:19], line[2:21]]
        for date in dates:
            try:
                datetime.strptime(date, "%Y-%m-%dT%H:%M:%S")
                if date > start and date < end:
                    if line[0] == "|":  # sm-customer.log edge case
                        line = line[1:].strip()
                        line = re.sub("\\s+", " ", line)
                    data.append(line)
                break
            except ValueError:
                if date == dates[-1]:
                    data.append(line)
