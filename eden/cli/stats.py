#!/usr/bin/env python3
#
# Copyright (c) 2004-present, Facebook, Inc.
# All rights reserved.
#
# This source code is licensed under the BSD-style license found in the
# LICENSE file in the root directory of this source tree. An additional grant
# of patent rights can be found in the PATENTS file in the same directory.

import argparse
import sys
from typing import Dict, Tuple
from . import cmd_util
from . import stats_print

DiagInfoCounters = Dict[str, int]
Table = Dict[str, Tuple[int, int, int, int]]


# Gets Information like memory usage, List of mount points and number of Inodes
# loaded, unloaded and materialized in the mount points etc.
def do_stats_general(args: argparse.Namespace):
    out = sys.stdout
    stats_print.write_heading('General Stat Information for EdenFs', out)
    config = cmd_util.create_config(args)

    with config.get_thrift_client() as client:
        diag_info = client.getStatInfo()
        stats_print.write_mem_status_table(diag_info.counters, out)
        format_str = '{:>40} {:^1} {:<20}\n'

        # Print Inodes unloaded by unload Job.
        out.write(
            format_str.format(
                'Inodes unloaded by Periodic Job', ':', '%d\n' %
                diag_info.periodicUnloadCount
            )
        )
        # print InodeInfo for all the mountPoints
        inode_info = diag_info.mountPointInfo
        for key in inode_info:
            out.write('MountPoint Information for %s\n' % key)
            out.write(
                'Loaded Inodes in memory          : %d\n' %
                inode_info[key].loadedInodeCount
            )
            out.write(
                'Unloaded Inodes in memory        : %d\n' %
                inode_info[key].unloadedInodeCount
            )
            out.write(
                'Materialized Inodes in memory    : %d\n\n' %
                inode_info[key].materializedInodeCount
            )


# Function that shows memory related informtion like memory usage, free memory
# etc
def do_stats_memory(args: argparse.Namespace):
    out = sys.stdout
    stats_print.write_heading('Memory Stats for EdenFs', out)
    config = cmd_util.create_config(args)

    with config.get_thrift_client() as client:
        diag_info = client.getStatInfo()
        stats_print.write_mem_status_table(diag_info.counters, out)

        # print memory counters
        heading = 'Average values of Memory usage and availability'
        out.write('\n\n %s \n\n' % heading.center(80, ' '))

        mem_counters = get_memory_counters(diag_info.counters)
        stats_print.write_table(mem_counters, '', out)


# Returns all the memory counters in ServiceData in a table format.
def get_memory_counters(counters: DiagInfoCounters) -> Table:
    table = {}
    index = {'60': 0, '600': 1, '3600': 2}
    for key in counters:
        if key.startswith('memory') and key.find('.') != -1:
            tokens = key.split('.')
            memKey = tokens[0].replace('_', ' ')
            if memKey not in table.keys():
                table[memKey] = [0, 0, 0, 0]
            if len(tokens) == 2:
                table[memKey][3] = counters[key]
            else:
                table[memKey][index[tokens[2]]] = counters[key]
    return table


# Prints information about Number of times a system call is performed in EdenFs.
def do_stats_io(args: argparse.Namespace):
    out = sys.stdout
    stats_print.write_heading(
        'Counts of I/O operations performed in EdenFs', out
    )
    config = cmd_util.create_config(args)
    with config.get_thrift_client() as client:
        diag_info = client.getStatInfo()

        # If the arguments has --all flag, we will have args.all set to true.
        fuse_counters = get_fuse_counters(diag_info.counters, args.all)
        stats_print.write_table(fuse_counters, 'SystemCall', out)


# Filters Fuse counters from all the counters in ServiceData and returns a
# printable form of the information in a table. If all_flg is true we get the
# counters for all the system calls, otherwise we get the counters of the
# system calls which are present in the list syscalls, which is a list of
# frequently called io system calls.
def get_fuse_counters(counters: DiagInfoCounters, all_flg: bool) -> Table:
    table = {}
    index = {'60': 0, '600': 1, '3600': 2}

    # list of io system calls, if all flag is set we return counters for all the
    # systems calls, else we return counters for io systemcalls.
    syscalls = [
        'open', 'read', 'write', 'symlink', 'readlink', 'mkdir', 'mknod',
        'opendir', 'readdir', 'rmdir'
    ]

    for key in counters:
        if key.startswith('fuse') and key.find('.count') >= 0:
            tokens = key.split('.')
            syscall = tokens[1][:-3]  # _us
            if not all_flg and syscall not in syscalls:
                continue

            if syscall not in table.keys():
                table[syscall] = [0, 0, 0, 0]
            if len(tokens) == 3:
                table[syscall][3] = str(counters[key])
            else:
                table[syscall][index[tokens[3]]] = str(counters[key])

    return table


# Prints the Latencies of system calls in EdenFs.
def do_stats_latency(args: argparse.Namespace):
    out = sys.stdout
    config = cmd_util.create_config(args)
    with config.get_thrift_client() as client:
        diag_info = client.getStatInfo()
        table = get_fuse_latency(diag_info.counters, args.all)
        stats_print.write_heading(
            'Latencies of I/O operations performed in EdenFs', out
        )
        stats_print.write_latency_table(table, out)


# Returns all the latency information in ServiceData in a table format.
# If all_flg is true we get the counters for all the system calls, otherwise we
# get the counters of the system calls which are present in the list syscalls,
# which is a list of frequently called io system calls.
def get_fuse_latency(counters: DiagInfoCounters, all_flg: bool) -> Table:
    table = {}
    index = {'60': 0, '600': 1, '3600': 2}
    percentile = {'p50': 0, 'p90': 1, 'p99': 2}
    syscalls = [
        'open', 'read', 'write', 'symlink', 'readlink', 'mkdir', 'mknod',
        'opendir', 'readdir', 'rmdir'
    ]

    def with_microsecond_units(i):
        if i:
            return str(i) + u" \u03BCs"  # mu for micro
        else:
            return str(i) + '   '

    for key in counters:
        if key.startswith('fuse') and key.find('.count') == -1:
            tokens = key.split('.')
            syscall = tokens[1][:-3]
            if not all_flg and syscall not in syscalls:
                continue
            if syscall not in table.keys():
                table[syscall] = [[0, 0, 0, 0], [0, 0, 0, 0], [0, 0, 0, 0]]
            i = percentile[tokens[2]]
            j = 3
            if len(tokens) > 3:
                j = index[tokens[3]]
            table[syscall][i][j] = with_microsecond_units(counters[key])
    return table


def do_stats_thrift(args: argparse.Namespace):
    out = sys.stdout
    stats_print.write_heading('Counts of Thrift calls performed in EdenFs', out)
    config = cmd_util.create_config(args)
    with config.get_thrift_client() as client:
        diag_info = client.getStatInfo()

        thrift_counters = get_thrift_counters(diag_info.counters)
        stats_print.write_table(thrift_counters, 'Thrift Call', out)


def get_thrift_counters(counters: DiagInfoCounters) -> Table:
    table = {}

    for key in counters:
        segments = key.split('.')
        if (len(segments) == 5 and
                segments[:2] == ['thrift', 'EdenService'] and
                segments[-2:] == ['num_calls', 'sum']):
            call_name = segments[2]
            last_minute = counters[key + '.60']
            last_10_minutes = counters[key + '.600']
            last_hour = counters[key + '.3600']
            all_time = counters[key]
            table[call_name] = [
                last_minute, last_10_minutes, last_hour, all_time
            ]

    return table


def setup_argparse(parser: argparse.ArgumentParser):
    subparsers = parser.add_subparsers(dest='subparser_name')

    parser = subparsers.add_parser(
        'io',
        help='Shows status about number calls made for each io systemcall'
    )
    parser.add_argument(
        '-A',
        '--all',
        action='store_true',
        default=False,
        help='Show status for all the system calls'
    )
    parser.set_defaults(func=do_stats_io)

    parser = subparsers.add_parser(
        'latency', help='Shows latency report for io systemcalls'
    )
    parser.add_argument(
        '-A',
        '--all',
        action='store_true',
        default=False,
        help='Show status for all the system calls'
    )
    parser.set_defaults(func=do_stats_latency)

    parser = subparsers.add_parser(
        'memory', help='Shows memory status of Edenfs'
    )
    parser.set_defaults(func=do_stats_memory)

    parser = subparsers.add_parser(
        'thrift', help='Shows number of thrift calls'
    )
    parser.set_defaults(func=do_stats_thrift)
