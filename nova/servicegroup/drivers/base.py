# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import random


class Driver(object):
    """Base class for all ServiceGroup drivers."""

    def join(self, member, group, service=None):
        """Add a new member to a service group.

        :param member: the joined member ID/name
        :param group: the group ID/name, of the joined member
        :param service: a `nova.service.Service` object
        """
        raise NotImplementedError()

    def is_up(self, member):
        """Check whether the given member is up."""
        raise NotImplementedError()

    def get_all(self, group_id):
        """Returns ALL members of the given group."""
        raise NotImplementedError()

    def get_one(self, group_id):
        """The default behavior of get_one is to randomly pick one from
        the result of get_all(). This is likely to be overridden in the
        actual driver implementation.
        """
        members = self.get_all(group_id)
        if members is None:
            return None
        length = len(members)
        if length == 0:
            return None
        return random.choice(members)
