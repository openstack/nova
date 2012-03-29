# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 OpenStack, LLC.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.


import os
import re


class CommandFilter(object):
    """Command filter only checking that the 1st argument matches exec_path"""

    def __init__(self, exec_path, run_as, *args):
        self.exec_path = exec_path
        self.run_as = run_as
        self.args = args

    def match(self, userargs):
        """Only check that the first argument (command) matches exec_path"""
        if (os.path.basename(self.exec_path) == userargs[0]):
            return True
        return False

    def get_command(self, userargs):
        """Returns command to execute (with sudo -u if run_as != root)."""
        if (self.run_as != 'root'):
            # Used to run commands at lesser privileges
            return ['sudo', '-u', self.run_as, self.exec_path] + userargs[1:]
        return [self.exec_path] + userargs[1:]

    def get_environment(self, userargs):
        """Returns specific environment to set, None if none"""
        return None


class RegExpFilter(CommandFilter):
    """Command filter doing regexp matching for every argument"""

    def match(self, userargs):
        # Early skip if command or number of args don't match
        if (len(self.args) != len(userargs)):
            # DENY: argument numbers don't match
            return False
        # Compare each arg (anchoring pattern explicitly at end of string)
        for (pattern, arg) in zip(self.args, userargs):
            try:
                if not re.match(pattern + '$', arg):
                    break
            except re.error:
                # DENY: Badly-formed filter
                return False
        else:
            # ALLOW: All arguments matched
            return True

        # DENY: Some arguments did not match
        return False


class DnsmasqFilter(CommandFilter):
    """Specific filter for the dnsmasq call (which includes env)"""

    def match(self, userargs):
        if (userargs[0].startswith("FLAGFILE=") and
            userargs[1].startswith("NETWORK_ID=") and
            userargs[2] == "dnsmasq"):
            return True
        return False

    def get_command(self, userargs):
        return [self.exec_path] + userargs[3:]

    def get_environment(self, userargs):
        env = os.environ.copy()
        env['FLAGFILE'] = userargs[0].split('=')[-1]
        env['NETWORK_ID'] = userargs[1].split('=')[-1]
        return env


class KillFilter(CommandFilter):
    """Specific filter for the kill calls.
       1st argument is a list of accepted signals (emptystring means no signal)
       2nd argument is a list of accepted affected executables.

       This filter relies on /proc to accurately determine affected
       executable, so it will only work on procfs-capable systems (not OSX).
    """

    def match(self, userargs):
        if userargs[0] != "kill":
            return False
        args = list(userargs)
        if len(args) == 3:
            signal = args.pop(1)
            if signal not in self.args[0]:
                # Requested signal not in accepted list
                return False
        else:
            if len(args) != 2:
                # Incorrect number of arguments
                return False
            if '' not in self.args[0]:
                # No signal, but list doesn't include empty string
                return False
        try:
            command = os.readlink("/proc/%d/exe" % int(args[1]))
            # NOTE(dprince): /proc/PID/exe may have ' (deleted)' on
            # the end if an executable is updated or deleted
            command = command.rstrip(" (deleted)")
            if command not in self.args[1]:
                # Affected executable not in accepted list
                return False
        except (ValueError, OSError):
            # Incorrect PID
            return False
        return True


class ReadFileFilter(CommandFilter):
    """Specific filter for the utils.read_file_as_root call"""

    def __init__(self, file_path, *args):
        self.file_path = file_path
        super(ReadFileFilter, self).__init__("/bin/cat", "root", *args)

    def match(self, userargs):
        if userargs[0] != 'cat':
            return False
        if userargs[1] != self.file_path:
            return False
        if len(userargs) != 2:
            return False
        return True
