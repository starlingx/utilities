########################################################################
#
# Copyright (c) 2022 Wind River Systems, Inc.
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
import algorithms
import json
import logging
import os

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
            "alarm_ids": [],
            "entity_ids": [],
            "start": None,
            "end": None,
        }
        if file:
            try:
                self._file_set_attributes()
            except KeyError as e:
                raise e
        elif opts:
            self._opts_set_attributes()

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

        # split string from first '=', left side is label right side is value
        data = line.strip().split("=", 1)
        if len(data) <= 1:
            raise ValueError("Value not specified for label")
        label = data[0]
        value = data[1]
        label = label.replace(" ", "")
        try:
            if label == "algorithm":
                self.state["algorithm"] = value.replace(" ", "")
            elif label == "substring":
                self.state["substring"].append(data[1])
            elif label == "hosts":
                self.state["hosts"] = value.replace(" ", "").split(",")
            elif label == "alarm_ids":
                self.state["alarm_ids"] = value.replace(" ", "").split(",")
            elif label == "entity_ids":
                self.state["entity_ids"] = value.replace(" ", "").split(",")
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

        if self.state["algorithm"] == algorithms.SUBSTRING:
            if len(self.state["files"]) == 0:
                raise ValueError(
                    f"plugin: {plugin_name} needs files specified for substring algorithm"
                )
            if len(self.state["hosts"]) == 0:
                raise ValueError(
                    f"plugin: {plugin_name} needs hosts specified for substring algorithm"
                )
            if len(self.state["substring"]) == 0:
                raise ValueError(
                    f"plugin: {plugin_name} need substring specified for substring algorithm"
                )
        elif self.state["algorithm"] == algorithms.ALARM:
            if len(self.state["hosts"]) > 0:
                raise ValueError(
                    f"plugin: {plugin_name} should not have hosts to be specified"
                )
        elif self.state["algorithm"] == algorithms.SYSTEM_INFO:
            if len(self.state["hosts"]) > 0:
                raise ValueError(
                    f"plugin: {plugin_name} should not have hosts to be specified"
                )
        elif self.state["algorithm"] == algorithms.SWACT:
            if len(self.state["hosts"]) > 0:
                raise ValueError(
                    f"plugin: {plugin_name} should not have hosts to be specified"
                )
        elif self.state["algorithm"] == algorithms.PUPPET:
            if len(self.state["hosts"]) > 0:
                raise ValueError(
                    f"plugin: {plugin_name} should not have hosts to be specified"
                )
        elif self.state["algorithm"] == algorithms.PROCESS_FAILURE:
            if len(self.state["hosts"]) > 0:
                raise ValueError(
                    f"plugin: {plugin_name} should not have hosts to be specified"
                )
        elif self.state["algorithm"] == algorithms.AUDIT:
            if len(self.state["hosts"]) > 0:
                raise ValueError(
                    f"plugin: {plugin_name} should not have hosts to be specified"
                )

            try:
                datetime.strptime(self.state["start"], "%Y-%m-%d %H:%M:%S")
            except:
                raise ValueError(
                    f"plugin : {plugin_name} needs a start time in YYYY-MM-DD HH:MM:SS format"
                )

            try:
                datetime.strptime(self.state["end"], "%Y-%m-%d %H:%M:%S")
            except:
                raise ValueError(
                    f"plugin : {plugin_name} needs an end time in YYYY-MM-DD HH:MM:SS format"
                )
        else:
            raise ValueError(
                f"plugin: {plugin_name} unknown algorithm {self.state['algorithm']}"
            )

        for host in self.state["hosts"]:
            if host not in ["controllers", "workers", "storages", "all"]:
                raise ValueError(
                    f"host not recognized: '{host}', accepted hosts are 'controllers', 'workers', 'storages', 'all'"
                )

    def __str__(self) -> str:
        return f"{json.dumps(self.state)} File: {self.file}"
