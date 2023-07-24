########################################################################
#
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# This file contains the functions for the alarm plugin algorithm.
#
# The alarm plugin algorithm gathers and presents a list of all alarms
# and customer logs, except those specified.
#
########################################################################

import os
import re


def alarm(host_dir, start, end, alarm_exclude=None,
          entity_exclude=None):
    """Alarm algorithm
    Presents all alarms and customer logs, except those specified

    Parameters:
        host_dir       (string): path to the host directory
        start          (string): Start time for analysis
        end            (string): End time for analysis

        alarm_exclude  (string list): List of alarms to ignore
        entity_exclude (string list): List of entity ids to ignore
    """
    alarm_data = {}
    log_data = {}

    fm_database = os.path.join(
        host_dir, "var", "extra", "database", "fm.db.sql.txt")
    if not os.path.exists(fm_database):
        return None, None

    if alarm_exclude is None:
        alarm_exclude = []
    if entity_exclude is None:
        entity_exclude = []

    with open(fm_database) as file:
        alarms_start = False
        for line in file:
            # start of event log
            if re.search(r"COPY (public\.)?event_log", line):
                alarms_start = True
            elif alarms_start and line == "\\.\n":
                break
            elif alarms_start:
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
                if start <= entry_date and entry_date <= end:
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
