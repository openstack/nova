# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import sys


class UUIDSentinels(object):
    def __init__(self):
        from oslo_utils import uuidutils
        self._uuid_module = uuidutils
        self._sentinels = {}

    def __getattr__(self, name):
        if name.startswith('_'):
            raise ValueError('Sentinels must not start with _')
        if name not in self._sentinels:
            self._sentinels[name] = self._uuid_module.generate_uuid()
        return self._sentinels[name]


sys.modules[__name__] = UUIDSentinels()
