################################################################################
# Copyright (c) 2022 Wind River Systems, Inc.
#
# SPDX-License-Identifier: Apache-2.0
#
################################################################################
import io
from io import BytesIO
import math
import os.path
import re
import shutil
import sys

import lz4.frame
import nsenter

from .common.constants import LOG

"""Dict with the file size properties containing the size type name and multiplier
in relation to the number of bytes that the size type contains.
"""
file_size_properties = {
    'b': {
        'id': 'b',
        'size': 'bytes',
        'multiplier': 1
    },
    'k': {
        'id': 'k',
        'size': 'kilobytes',
        'multiplier': 1024
    },
    'm': {
        'id': 'm',
        'size': 'megabytes',
        'multiplier': 1024 * 1024
    },
    'g': {
        'id': 'g',
        'size': 'gigabytes',
        'multiplier': 1024 * 1024 * 1024
    },
    '%': {
        'id': '%',
        'size': 'percentage',
        'multiplier': 1
    },
}


def parse_core_pattern(string_core_pattern, **kwargs):
    """Function that replaces core patterns with the actual information
    that is passed when the k8s handler is called.
    (see __main__.py for the list of args)

    Parameters
    ----------
    string_core_pattern : str
        The string containing the core pattern that will be parsed.
    kwargs : dict
        Dictionary with the args that were passed when calling the k8s handler

    Returns
    -------
    str
        String with all the information replaced accordingly
    """
    string_core_pattern = string_core_pattern.lower()
    LOG.info(f'Parsing core pattern: {string_core_pattern}')
    processed_string = string_core_pattern
    processed_string = processed_string.replace('%p', kwargs['pid'])
    processed_string = processed_string.replace('%u', kwargs['uid'])
    processed_string = processed_string.replace('%g', kwargs['gid'])
    processed_string = processed_string.replace('%s', kwargs['signal'])
    processed_string = processed_string.replace('%t', kwargs['timestamp'])
    processed_string = processed_string.replace('%h', kwargs['hostname'])
    processed_string = processed_string.replace('%e', kwargs['comm2'])
    LOG.info(f'Core pattern parsed to {processed_string}')
    return processed_string


def parse_size_config(string_config):
    """Function that parses the max file size configuration using a regex to separate the
    value and size type and finds the size type properties on the file_size_properties dict.

    e.g.
        string_config = 10m
        returns (10, {'size': 'megabytes','multiplier': 1024 * 1024})

    Parameters
    ----------
    string_config : str
        The string containing the core size configuration that will be parsed.

    Returns
    -------
    tuple(str, dict)
        Tuple with the value and file size properties(name of file size type and multiplier)
    """
    LOG.info(f'Parsing size config: {string_config}')
    match = re.match(r'(\d+(?:\.\d+)?)\s*([bkmgtp]|[BKMGTP]|\%)', string_config)
    if match:
        value = match.group(1)
        size_type_str = match.group(2)
        size_properties = file_size_properties[size_type_str.lower()]
        LOG.info(f'Size config parsed to {value} {size_properties["size"]} '
                 f'(Multiplier of bytes: {size_properties["multiplier"]})')
        return float(value), size_properties

    return None


def get_annotations_config(pod_data):
    """Function that get all the configurations from the pod annotations

    Parameters
    ----------
    pod_data : dict
        Dict containing the pod information

    Returns
    -------
    dict
        Dictionary with all the annotations configurations
    """
    LOG.info('Getting annotations config')
    metadata = pod_data['metadata']
    annotations = metadata['annotations']
    dict_with_config = {
        "core_pattern": annotations.get("starlingx.io/core_pattern"),
        "file_size_config": annotations.get("starlingx.io/core_max_size"),
        "file_compression_config": annotations.get("starlingx.io/core_compression"),
        "max_use_config": annotations.get("starlingx.io/core_max_used"),
        "keep_free_config": annotations.get("starlingx.io/core_min_free"),
    }
    LOG.info(f'Annotations config: {dict_with_config}')
    return dict_with_config


def check_available_space(path):
    """Function that get the space information(total, used and free space) on the path provided

    Parameters
    ----------
    path : str
        The path that will be analyzed the disk usage.

    Returns
    -------
    dict
        Dictionary with the total space, used space and free space for the path provided
    """
    try:
        LOG.info(f'Checking available space on {path}')
        total, used, free = shutil.disk_usage(path)

        space_info = {
            "total_space": total,
            "used_space": used,
            "free_space": free,
        }
        LOG.info(
            f'Space info for {path}: Total - {total} bytes | '
            f'Used - {used} bytes ({"%.2f" % ((used * 100) / total)} %) | '
            f'Free - {free} bytes ({"%.2f" % ((free * 100) / total)} %)')
        return space_info
    except FileNotFoundError as e:
        LOG.error("Failed to check disk usage in path {}: {}".format(path, e))
        sys.exit(-1)


def convert_from_bytes(bytes_amount, size_to_convert):
    """Function that converts a value of bytes to other size value
    e.g.
        bytes_amount = 3.145.728
        size_to_convert = 'm'
        returns 3 (Which means that 3.145.728 bytes = 3 MB)

    Parameters
    ----------
    bytes_amount : int
        Number of bytes
    size_to_convert : str
        Which size type should be converted to

    Returns
    -------
    int
        Converted amount of the size type requested
    """
    return bytes_amount / file_size_properties[size_to_convert]['multiplier']


def convert_to_bytes(amount, size_from_convert):
    """Function that converts a value of a size type to the equivalent byte amount
    e.g.
        amount = 3
        size_to_convert = 'm'
        returns 3.145.728 (Which means that 3 MB = 3.145.728 bytes)

    Parameters
    ----------
    amount : int
        Number of the size type
    size_from_convert : str
        Which size type should be converted from

    Returns
    -------
    int
        Converted amount of bytes from the size type informed
    """
    return amount * file_size_properties[size_from_convert]['multiplier']


def write_coredump_file(pid, corefile, annotations_config):
    """Function that writes the coredump file inside the pod using the namespace of the pod.

    Parameters
    ----------
    pid : str
        Pod process PID
    corefile : str
        File name and path to save the coredump file
    annotations_config : dict
        Dictionary containing the annotations configuration

    Returns
    -------
    No return
    """
    LOG.info(f'Starting to write coredump file {corefile}')
    use_compression = True if annotations_config['file_compression_config'] == 'lz4' else False
    size_limit_in_bytes = get_file_size_limit(corefile, annotations_config, pid)
    buffer_read_size = math.ceil(size_limit_in_bytes / 2) if size_limit_in_bytes > 0 else None
    LOG.info(f'Configurations: Use compression? {"Yes" if use_compression else "No"} | '
             f'Size limit? {size_limit_in_bytes if size_limit_in_bytes > 0 else "No size limit"} |'
             f'Buffer read size = {buffer_read_size}')

    with nsenter.Namespace(pid, 'mnt'):
        LOG.info(f'Entered namespace for pid = {pid}')
        try:
            with io.open(corefile, "wb") as f:
                bytes_written = 0
                if use_compression:
                    compressed_bytes = lz4.frame.compress(sys.stdin.buffer.read())
                    file_to_read = BytesIO(compressed_bytes)
                    LOG.info('Compressed file with lz4 algorithm')
                else:
                    file_to_read = sys.stdin.buffer
                while True:
                    buffer = file_to_read.read(buffer_read_size) if buffer_read_size else file_to_read.read()
                    if buffer and (size_limit_in_bytes == 0 or bytes_written < size_limit_in_bytes):
                        f.write(buffer)
                        bytes_written = f.tell()
                    else:
                        break
                f.flush()
                LOG.info(f'Finished writing coredump file {corefile}')
        except IOError as e:
            LOG.error("failed to create core file: {}".format(e))
            sys.exit(-1)


def get_percentage_byte_value(value, space_info):
    """Function that calculates a percentage from the total space given a value.

    Parameters
    ----------
    value : int
        Amount of bytes
    space_info : dict
        Information of the disk space (total, available, used)

    Returns
    -------
    Percentage of bytes in the total space
    """
    return (value / 100) * space_info['total_space']


def get_file_size_limit(corefile, annotations_config, pid):
    """Function that calculates the size limit of the coredump file
    using the configurations from the annotations and the available, used
    and total space of the corefile path.

    Parameters
    ----------
    corefile : str
        File name and path to save the coredump file
    annotations_config : dict
        Dictionary containing the annotations configuration
    pid : str
        Pod process PID

    Returns
    -------
    Value of the calculated size limit or 0 if no limit is set.
    """
    # Enter namespace to check size inside the container
    with nsenter.Namespace(pid, 'mnt'):
        # Set starting information
        core_path = os.path.dirname(corefile)
        space_info = check_available_space(core_path)
    has_max_file_config = False
    has_max_use_config = False
    has_keep_free_config = False
    max_file_size_bytes = 0
    max_use_bytes = 0
    keep_free_bytes = 0
    file_size_config = {}
    max_use_config = {}
    keep_free_config = {}

    # Get configurations values if there's a configuration set
    if annotations_config['file_size_config']:
        file_size_config = parse_size_config(annotations_config['file_size_config'])
        if not file_size_config:
            LOG.error("Invalid starlingx.io/core_max_size configuration: {}".format(
                annotations_config['file_size_config']))
            sys.exit(-1)
        has_max_file_config = True

    if annotations_config['max_use_config']:
        max_use_config = parse_size_config(annotations_config['max_use_config'])
        if not max_use_config:
            LOG.error("Invalid starlingx.io/core_max_used configuration: {}".format(
                annotations_config['max_use_config']))
            sys.exit(-1)
        has_max_use_config = True

    if annotations_config['keep_free_config']:
        keep_free_config = parse_size_config(annotations_config['keep_free_config'])
        if not keep_free_config:
            LOG.error("Invalid starlingx.io/core_min_free configuration: {}".format(
                annotations_config['keep_free_config']))
            sys.exit(-1)
        has_keep_free_config = True

    # If there's no size configuration return 0 to not limit the file size.
    if not (has_max_file_config or has_max_use_config or has_keep_free_config):
        return 0

    # Convert all values into bytes
    if has_max_file_config:
        if file_size_config[1]['id'] != '%':
            max_file_size_bytes = convert_to_bytes(file_size_config[0], file_size_config[1]['id'])
        else:
            max_file_size_bytes = get_percentage_byte_value(file_size_config[0], space_info)

    if has_max_use_config:
        if max_use_config[1]['id'] != '%':
            max_use_bytes = convert_to_bytes(max_use_config[0], max_use_config[1]['id'])
        else:
            max_use_bytes = get_percentage_byte_value(max_use_config[0], space_info)
        if max_use_bytes <= space_info['used_space']:
            if max_use_config[1]['id'] != '%':
                used_space_converted = str(convert_from_bytes(space_info['used_space'], max_use_config[1]['id'])) + \
                    max_use_config[1]['id']
            else:
                used_space_converted = space_info['used_space']
            LOG.error(f"Max use of disk reached, can't save coredump. (Max use configured is {max_use_config} "
                      f"and disk used space is {used_space_converted})")
            sys.exit(-1)
        max_use_bytes = max_use_bytes - space_info['used_space']

    if has_keep_free_config:
        if keep_free_config[1]['id'] != '%':
            keep_free_bytes = convert_to_bytes(keep_free_config[0], keep_free_config[1]['id'])
        else:
            keep_free_bytes = get_percentage_byte_value(keep_free_config[0], space_info)
        if keep_free_bytes >= space_info['free_space']:
            if keep_free_config[1]['id'] != '%':
                free_space_converted = str(convert_from_bytes(space_info['free_space'], keep_free_config[1]['id'])) + \
                    keep_free_config[1]['id']
            else:
                free_space_converted = space_info['free_space']
            LOG.error(
                f"Reached keep free space limit, can't save coredump. (Keep free configured is {keep_free_config} "
                f"and disk free space is {free_space_converted})")
            sys.exit(-1)
        keep_free_bytes = space_info['free_space'] - keep_free_bytes

    # Set any value that's not configured to infinite so the min function will get the smaller size.
    max_file_size_bytes = max_file_size_bytes if has_max_file_config else float("inf")
    max_use_bytes = max_use_bytes if has_max_use_config else float("inf")
    keep_free_bytes = keep_free_bytes if has_keep_free_config else float("inf")

    return int(min([max_file_size_bytes, max_use_bytes, keep_free_bytes]))
