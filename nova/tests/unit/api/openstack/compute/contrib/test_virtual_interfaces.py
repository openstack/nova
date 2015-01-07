# Copyright (C) 2011 Midokura KK
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

import webob

from nova.api.openstack.compute.contrib import virtual_interfaces as vi20
from nova.api.openstack.compute.plugins.v3 import virtual_interfaces as vi21
from nova import compute
from nova.compute import api as compute_api
from nova import context
from nova import exception
from nova import network
from nova import test
from nova.tests.unit.api.openstack import fakes


FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'


def compute_api_get(self, context, instance_id, expected_attrs=None,
                    want_objects=False):
    return dict(uuid=FAKE_UUID, id=instance_id, instance_type_id=1, host='bob')


def get_vifs_by_instance(self, context, instance_id):
    return [{'uuid': '00000000-0000-0000-0000-00000000000000000',
             'address': '00-00-00-00-00-00'},
            {'uuid': '11111111-1111-1111-1111-11111111111111111',
             'address': '11-11-11-11-11-11'}]


class FakeRequest(object):
    def __init__(self, context):
        self.environ = {'nova.context': context}


class ServerVirtualInterfaceTestV21(test.NoDBTestCase):

    def setUp(self):
        super(ServerVirtualInterfaceTestV21, self).setUp()
        self.stubs.Set(compute.api.API, "get",
                       compute_api_get)
        self.stubs.Set(network.api.API, "get_vifs_by_instance",
                       get_vifs_by_instance)
        self._set_controller()

    def _set_controller(self):
        self.controller = vi21.ServerVirtualInterfaceController()

    def test_get_virtual_interfaces_list(self):
        req = fakes.HTTPRequest.blank('')
        res_dict = self.controller.index(req, 'fake_uuid')
        response = {'virtual_interfaces': [
                        {'id': '00000000-0000-0000-0000-00000000000000000',
                         'mac_address': '00-00-00-00-00-00'},
                        {'id': '11111111-1111-1111-1111-11111111111111111',
                         'mac_address': '11-11-11-11-11-11'}]}
        self.assertEqual(res_dict, response)

    def test_vif_instance_not_found(self):
        self.mox.StubOutWithMock(compute_api.API, 'get')
        fake_context = context.RequestContext('fake', 'fake')
        fake_req = FakeRequest(fake_context)

        compute_api.API.get(fake_context, 'fake_uuid',
                            expected_attrs=None,
                            want_objects=True).AndRaise(
            exception.InstanceNotFound(instance_id='instance-0000'))

        self.mox.ReplayAll()
        self.assertRaises(
            webob.exc.HTTPNotFound,
            self.controller.index,
            fake_req, 'fake_uuid')


class ServerVirtualInterfaceTestV20(ServerVirtualInterfaceTestV21):

    def _set_controller(self):
        self.controller = vi20.ServerVirtualInterfaceController()
