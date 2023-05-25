########################################################################
#
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# This file contains the functions for the audit plugin algorithm.
#
# The audit plugin algorithm counts the audit events found in dcmanager
# within a specific date range.
#
########################################################################

from datetime import datetime
import shutil
import subprocess


def audit(start, end, audit_log_path):
    """Counts audit events, like "Trigger load audit", in dcmanager within a
    specified date range

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
    data = [("These rates and totals represent the sum of audits " +
             "from all subclouds")]

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
