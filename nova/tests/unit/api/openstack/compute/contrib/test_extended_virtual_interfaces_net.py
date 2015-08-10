# Copyright 2013 IBM Corp.
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

from oslo_serialization import jsonutils
import webob

from nova.api.openstack.compute.legacy_v2.contrib import \
    extended_virtual_interfaces_net
from nova import compute
from nova import network
from nova.objects import virtual_interface as vif_obj
from nova import test
from nova.tests.unit.api.openstack import fakes


FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'

EXPECTED_NET_UUIDS = [123,
                      456]


def _generate_fake_vifs(context):
    vif = vif_obj.VirtualInterface(context=context)
    vif.address = '00-00-00-00-00-00'
    vif.net_uuid = 123
    vif.uuid = '00000000-0000-0000-0000-00000000000000000'
    fake_vifs = [vif]
    vif = vif_obj.VirtualInterface(context=context)
    vif.address = '11-11-11-11-11-11'
    vif.net_uuid = 456
    vif.uuid = '11111111-1111-1111-1111-11111111111111111'
    fake_vifs.append(vif)
    return fake_vifs


def compute_api_get(self, context, instance_id, expected_attrs=None,
                    want_objects=False):
    return dict(uuid=FAKE_UUID, id=instance_id, instance_type_id=1, host='bob')


def get_vifs_by_instance(self, context, instance_id):
    return _generate_fake_vifs(context)


def get_vif_by_mac_address(self, context, mac_address):
    if mac_address == "00-00-00-00-00-00":
        return _generate_fake_vifs(context)[0]
    else:
        return _generate_fake_vifs(context)[1]


class ExtendedServerVIFNetTest(test.NoDBTestCase):
    content_type = 'application/json'
    prefix = "%s:" % extended_virtual_interfaces_net. \
                        Extended_virtual_interfaces_net.alias

    def setUp(self):
        super(ExtendedServerVIFNetTest, self).setUp()
        self.stubs.Set(compute.api.API, "get",
                       compute_api_get)
        self.stubs.Set(network.api.API, "get_vifs_by_instance",
                       get_vifs_by_instance)
        self.stubs.Set(network.api.API, "get_vif_by_mac_address",
                       get_vif_by_mac_address)
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Virtual_interfaces',
                                    'Extended_virtual_interfaces_net'])

    def _make_request(self, url):
        req = webob.Request.blank(url)
        req.headers['Accept'] = self.content_type
        res = req.get_response(fakes.wsgi_app(init_only=(
                                 'os-virtual-interfaces', 'OS-EXT-VIF-NET')))
        return res

    def _get_vifs(self, body):
        return jsonutils.loads(body).get('virtual_interfaces')

    def _get_net_id(self, vifs):
        for vif in vifs:
            yield vif['%snet_id' % self.prefix]

    def assertVIFs(self, vifs):
        result = []
        for net_id in self._get_net_id(vifs):
            result.append(net_id)
        sorted(result)

        for i, net_uuid in enumerate(result):
            self.assertEqual(net_uuid, EXPECTED_NET_UUIDS[i])

    def test_get_extend_virtual_interfaces_list(self):
        res = self._make_request('/v2/fake/servers/abcd/os-virtual-interfaces')

        self.assertEqual(res.status_int, 200)
        self.assertVIFs(self._get_vifs(res.body))
