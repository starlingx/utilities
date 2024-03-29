########################################################################
#
# Copyright (c) 2022 - 2023 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
########################################################################
#
# This file contains the Plugin class.
# The Plugin class contains all the labels and information of a plugin.
#
# Plugins contain labels to instruct the execution engine what to search
# for and where to search.
#
########################################################################

from datetime import datetime
import json
import logging
import os

import algorithms

logger = logging.getLogger(__name__)


class Plugin:
    def __init__(self, file="", opts=None):
        """Constructor for the Plugin class

        Parameters:
            file (string)    : Absolute filepath of the plugin
            opts (dictionary): Options from command line when running algorithm
        """
        self.file = file
        self.opts = opts
        self.state = {
            "algorithm": None,
            "files": [],
            "hosts": [],
            "substring": [],
            "exclude": [],
            "alarm_exclude": [],
            "entity_exclude": [],
            "start": None,
            "end": None,
        }
        logger.debug("plugin init: %s", file)
        if file and os.path.isfile(file):
            try:
                logger.debug("calling _file_set_attributes file: %s", file)
                self._file_set_attributes()
            except KeyError as e:
                raise e
        elif opts:
            logger.debug("calling _opts_set_attributes opts: %s", self.opts)
            self._opts_set_attributes()
        else:
            logger.debug("no plugin opts specified")

        try:
            self.verify()
        except ValueError as e:
            raise e

    def _file_set_attributes(self):
        """Sets plugin attributes from plugin files"""
        with open(self.file) as f:
            for line in f:
                try:
                    self.extract(line)
                except Exception as e:
                    raise e

    def _opts_set_attributes(self):
        """Sets plugin attributes from command line options"""
        for k, v in self.opts.items():
            self.state[k] = v

    def extract(self, line):
        """Extracts and sets attributes for this plugin

        Parameters:
            line (string): Line from plugin file to extract
        """

        # allow plugins to have empty lines or comments starting with #
        if len(line) <= 1 or line[0] == '#':
            return

        # split string from first '=', left side is label right side is value
        data = line.strip().split("=", 1)
        if len(data) <= 1:
            raise ValueError("Value not specified for label")
        label = data[0]
        value = data[1]
        label = label.replace(" ", "")

        # ignore labels that don't start with an alphabetical char
        if label[0].isalpha() is False:
            raise ValueError("Invalid label value")
        try:
            if label == "algorithm":
                self.state["algorithm"] = value.replace(" ", "")
            elif label == "substring":
                self.state["substring"].append(data[1])
            elif label == "exclude":
                self.state["exclude"].append(data[1])
            elif label == "hosts":
                self.state["hosts"] = value.replace(" ", "").split(",")
            elif label == "alarm_exclude":
                self.state["alarm_exclude"] = value.replace(" ", "").split(",")
            elif label == "entity_exclude":
                self.state["entity_exclude"] = value.replace(
                    " ", "").split(",")
            elif label == "files":
                self.state["files"] = value.replace(" ", "").split(",")
            elif label == "start":
                self.state["start"] = value
            elif label == "end":
                self.state["end"] = value
            else:
                logger.warning("unknown label: %s", label)

        except KeyError:
            logger.warning("unknown label: %s", label)

    def verify(self):
        """Verify if this plugin's attributes are viable

        Errors:
            ValueError if a value is incorrectly set
        """

        plugin_name = os.path.basename(self.file)
        HOSTS_ERR = f"plugin: '{plugin_name}' shouldn't have 'hosts' label"

        if self.state["algorithm"] == algorithms.SUBSTRING:
            self.validate_state(plugin_name, "files")
            self.validate_state(plugin_name, "hosts")
            self.validate_state(plugin_name, "substring")
        elif self.state["algorithm"] == algorithms.ALARM:
            if len(self.state["hosts"]) > 0:
                raise ValueError(HOSTS_ERR)
        elif self.state["algorithm"] == algorithms.SYSTEM_INFO:
            if len(self.state["hosts"]) > 0:
                raise ValueError(HOSTS_ERR)
        elif self.state["algorithm"] == algorithms.SWACT_ACTIVITY:
            if len(self.state["hosts"]) > 0:
                raise ValueError(HOSTS_ERR)
        elif self.state["algorithm"] == algorithms.PUPPET_ERRORS:
            if len(self.state["hosts"]) > 0:
                raise ValueError(HOSTS_ERR)
        elif self.state["algorithm"] == algorithms.PROCESS_FAILURES:
            if len(self.state["hosts"]) > 0:
                raise ValueError(HOSTS_ERR)
        elif self.state["algorithm"] == algorithms.HEARTBEAT_LOSS:
            if len(self.state["hosts"]) > 0:
                raise ValueError(HOSTS_ERR)
        elif self.state["algorithm"] == algorithms.MAINTENANCE_ERR:
            if len(self.state["hosts"]) > 0:
                raise ValueError(HOSTS_ERR)
        elif self.state["algorithm"] == algorithms.DAEMON_FAILURES:
            if len(self.state["hosts"]) > 0:
                raise ValueError(HOSTS_ERR)
        elif self.state["algorithm"] == algorithms.STATE_CHANGES:
            if len(self.state["hosts"]) > 0:
                raise ValueError(HOSTS_ERR)
        elif self.state["algorithm"] == algorithms.AUDIT:
            if len(self.state["hosts"]) > 0:
                raise ValueError(HOSTS_ERR)

            try:
                datetime.strptime(self.state["start"], "%Y-%m-%d %H:%M:%S")
            except ValueError as e:
                logger.error(
                    "plugin '%s' needs a valid start time in YYYY-MM-DD \
                     HH:MM:SS format", plugin_name)

            try:
                datetime.strptime(self.state["end"], "%Y-%m-%d %H:%M:%S")
            except ValueError as e:
                logger.error(
                    "plugin '%s' needs a valid end time in YYYY-MM-DD \
                     HH:MM:SS format", plugin_name)

        else:
            raise ValueError(
                f"plugin: '{plugin_name}' algorithm label unsupported value: "
                f"{self.state['algorithm']}"
            )

        for host in self.state["hosts"]:
            if host not in ["controllers", "workers", "storages", "all"]:
                raise ValueError(
                    f"hosts label has unsupported values: '{host}', "
                    f"accepted hosts are "
                    f"'controllers', 'workers', 'storages', 'all'"
                )

    def validate_state(self, plugin_name, key):
        if len(self.state[key]) == 0:
            raise ValueError(
                f"plugin: {plugin_name} needs '{key}' label specified for "
                f"substring algorithm"
            )

    def __str__(self) -> str:
        return f"{json.dumps(self.state)} File: {self.file}"
