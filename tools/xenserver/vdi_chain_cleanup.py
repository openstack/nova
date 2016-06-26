#!/usr/bin/env python

# Copyright 2012 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
This script is designed to cleanup any VHDs (and their descendents) which have
a bad parent pointer.

The script needs to be run in the dom0 of the affected host.

The available actions are:

    - print: display the filenames of the affected VHDs
    - delete: remove the affected VHDs
    - move: move the affected VHDs out of the SR into another directory
"""
import glob
import os
import subprocess
import sys


class ExecutionFailed(Exception):
    def __init__(self, returncode, stdout, stderr, max_stream_length=32):
        self.returncode = returncode
        self.stdout = stdout[:max_stream_length]
        self.stderr = stderr[:max_stream_length]
        self.max_stream_length = max_stream_length

    def __repr__(self):
        return "<ExecutionFailed returncode=%s out='%s' stderr='%s'>" % (
            self.returncode, self.stdout, self.stderr)

    __str__ = __repr__


def execute(cmd, ok_exit_codes=None):
    if ok_exit_codes is None:
        ok_exit_codes = [0]

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    (stdout, stderr) = proc.communicate()

    if proc.returncode not in ok_exit_codes:
        raise ExecutionFailed(proc.returncode, stdout, stderr)

    return proc.returncode, stdout, stderr


def usage():
    print("usage: %s <SR PATH> <print|delete|move>" % sys.argv[0])
    sys.exit(1)


def main():
    if len(sys.argv) < 3:
        usage()

    sr_path = sys.argv[1]
    action = sys.argv[2]

    if action not in ('print', 'delete', 'move'):
        usage()

    if action == 'move':
        if len(sys.argv) < 4:
            print("error: must specify where to move bad VHDs")
            sys.exit(1)

        bad_vhd_path = sys.argv[3]
        if not os.path.exists(bad_vhd_path):
            os.makedirs(bad_vhd_path)

    bad_leaves = []
    descendents = {}

    for fname in glob.glob(os.path.join(sr_path, "*.vhd")):
        (returncode, stdout, stderr) = execute(
            ['vhd-util', 'query', '-n', fname, '-p'], ok_exit_codes=[0, 22])

        stdout = stdout.strip()

        if stdout.endswith('.vhd'):
            try:
                descendents[stdout].append(fname)
            except KeyError:
                descendents[stdout] = [fname]
        elif 'query failed' in stdout:
            bad_leaves.append(fname)

    def walk_vhds(root):
        yield root
        if root in descendents:
            for child in descendents[root]:
                for vhd in walk_vhds(child):
                    yield vhd

    for bad_leaf in bad_leaves:
        for bad_vhd in walk_vhds(bad_leaf):
            print(bad_vhd)
            if action == "print":
                pass
            elif action == "delete":
                os.unlink(bad_vhd)
            elif action == "move":
                new_path = os.path.join(bad_vhd_path,
                                        os.path.basename(bad_vhd))
                os.rename(bad_vhd, new_path)
            else:
                raise Exception("invalid action %s" % action)


if __name__ == '__main__':
    main()
