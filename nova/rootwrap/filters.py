# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Openstack, LLC.
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
        return userargs[0:2] + [self.exec_path] + userargs[3:]
