# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

import unittest

from nova.api.rackspace import servers
from nova.tests.api.test_helper import *

class ServersTest(unittest.TestCase):
    def setUp(self):
        self.stubs = stubout.StubOutForTesting()

    def tearDown(self):
        self.stubs.UnsetAll()

    def test_get_server_list(self):
        pass

    def test_create_instance(self):
        pass

    def test_get_server_by_id(self):
        pass

    def test_get_server_details(self):
        pass

    def test_get_server_ips(self):
        pass

    def test_server_reboot(self):
        pass

    def test_server_rebuild(self):
        pass

    def test_server_resize(self):
        pass

    def test_delete_server_instance(self):
        pass
