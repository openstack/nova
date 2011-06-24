# Copyright 2011 Eldar Nugaev
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
from nova import context
from nova import db
from nova import test
<<<<<<< TREE
from nova.api.openstack.contrib.floating_ips import FloatingIPController
=======
from nova import network
from nova.tests.api.openstack import fakes

import stubout
import webob

>>>>>>> MERGE-SOURCE
from nova.api.openstack.contrib.floating_ips import \
    _translate_floating_ip_view

def network_api_get():
    pass

def network_api_list():
    pass

def network_api_allocate():
    pass

def network_api_release():
    pass

def network_api_associate():
    pass

def network_api_disassociate():
    pass


class FloatingIpTest(test.TestCase):
    address = "10.10.10.10"

    def _create_floating_ip(self):
        """Create a volume object."""
        host = "fake_host"
        return db.floating_ip_create(self.context,
                                     {'address': self.address,
                                      'host': host})

    def setUp(self):
        super(FloatingIpTest, self).setUp()
        self.stubs = stubout.StubOutForTesting()
        fakes.FakeAuthManager.reset_fake_data()
        fakes.FakeAuthDatabase.data = {}
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_auth(self.stubs)
        self.stubs.Set(network.api, "get",
                       network_api_get)
        self.stubs.Set(network.api, "list",
                       network_api_list)
        self.stubs.Set(network.api, "allocate_floating_ip",
                       network_api_allocate)
        self.stubs.Set(network.api, "release_floating_ip",
                       network_api_release)
        self.stubs.Set(network.api, "associate_floating_ip",
                       network_api_associate)
        self.stubs.Set(network.api, "disassociate_floating_ip",
                       network_api_disassociate)
        self.context = context.get_admin_context()

    def tearDown(self):
        self.stubs.UnsetAll()
        super(FloatingIpTest, self).tearDown()

    def test_translate_floating_ip_view(self):
        floating_ip_address = self._create_floating_ip()
        floating_ip = db.floating_ip_get_by_address(self.context,
                                                    floating_ip_address)
        view = _translate_floating_ip_view(floating_ip)
        self.assertTrue('floating_ip' in view)
        self.assertTrue(view['floating_ip']['id'])
        self.assertEqual(view['floating_ip']['ip'], self.address)
        self.assertEqual(view['floating_ip']['fixed_ip'], None)
        self.assertEqual(view['floating_ip']['instance_id'], None)

    def test_translate_floating_ips_view(self):
        pass

    def test_floating_ips_list(self):
        pass

    def test_floating_ip_show(self):
        pass

    def test_floating_ip_allocate(self):
        pass

    def test_floating_ip_release(self):
        pass

    def test_floating_ip_associate(self):
        pass

    def test_floating_ip_disassociate(self):
        pass