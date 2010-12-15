# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Super simple fake memcache client."""


class Client(object):
    """Replicates a tiny subset of memcached client interface."""
    __cache = {}

    def __init__(self, *args, **kwargs):
        """Ignores all constructor params."""
        pass

    def get(self, key):
        """Retrieves the value for a key or None."""
        return self.__cache.get(key, None)

    def set(self, key, value):
        """Sets the value for a key."""
        self.__cache[key] = value
        return True

    def add(self, key, value):
        """Sets the value for a key if it doesn't exist."""
        if key in self.__cache:
            return False
        return self.set(key, value)

    def incr(self, key, delta=1):
        """Increments the value for a key."""
        if not key in self.__cache:
            return 0
        self.__cache[key] = str(int(self.__cache[key]) + 1)
        return self.__cache[key]
