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

import testtools

from oslo_utils import uuidutils

from nova.tests import uuidsentinel


class TestUUIDSentinels(testtools.TestCase):
    def test_different_sentinel(self):
        uuid1 = uuidsentinel.foobar
        uuid2 = uuidsentinel.barfoo
        self.assertNotEqual(uuid1, uuid2)

    def test_returns_uuid(self):
        self.assertTrue(uuidutils.is_uuid_like(uuidsentinel.foo))

    def test_returns_string(self):
        self.assertIsInstance(uuidsentinel.foo, str)
