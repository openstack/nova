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
import webob
from nova.api.openstack.contrib.floating_ips import FloatingIPController
from nova.api.openstack.contrib.floating_ips import \
    _translate_floating_ip_view


class FloatingIpTest(test.TestCase):
    floating_ip_address = "10.10.10.10"
    fixed_ip_address = '100.100.100.100'

    def _create_fixed_ip(self):
        """Create a fixed ip object. Returns address as string"""
        return db.fixed_ip_create(self.context, {'address': self.floating_ip_address})

    def _create_floating_ip(self):
        """Create a floating ip object. Returns address as string"""
        return db.floating_ip_create(self.context, {'address': self.floating_ip_address, })

    def setUp(self):
        super(FloatingIpTest, self).setUp()
        self.controller = FloatingIPController()
        self.context = context.get_admin_context()

    def test_translate_floating_ip_view(self):
        floating_ip_address = self._create_floating_ip()
        floating_ip = db.floating_ip_get_by_address(self.context,
                                                    floating_ip_address)
        view = _translate_floating_ip_view(floating_ip)
        self.assertTrue('floating_ip' in view)
        self.assertTrue(view['floating_ip']['id'])
        self.assertEqual(view['floating_ip']['ip'], self.floating_ip_address)
        self.assertEqual(view['floating_ip']['fixed_ip'], None)
        self.assertEqual(view['floating_ip']['instance_id'], None)

    def test_associate_by_address(self):
        fixed_ip_address = self._create_fixed_ip()
        floating_ip_address = self._create_floating_ip()
        floating_ip = db.floating_ip_get_by_address(self.context, floating_ip_address)

        self.assertEqual(floating_ip['address'], self.floating_ip_address)
        self.assertEqual(floating_ip['fixed_ip_id'], None)
        body = {'associate_address': {'fixed_ip': self.fixed_ip_address}}

        req = webob.Request.blank('/v1.1/floating_ips//associate')
        raise Exception(req.__dict__)
        #self.controller.associate(req, self.floating_ip_address, body)
        #self.assertEqual(floating_ip['fixed_ip'], self.fixed_ip_address)

