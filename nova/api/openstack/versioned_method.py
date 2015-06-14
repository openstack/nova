# Copyright 2014 IBM Corp.
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


class VersionedMethod(object):

    def __init__(self, name, start_version, end_version, func):
        """Versioning information for a single method

        @name: Name of the method
        @start_version: Minimum acceptable version
        @end_version: Maximum acceptable_version
        @func: Method to call

        Minimum and maximums are inclusive
        """
        self.name = name
        self.start_version = start_version
        self.end_version = end_version
        self.func = func

    def __str__(self):
        return ("Version Method %s: min: %s, max: %s"
                % (self.name, self.start_version, self.end_version))
