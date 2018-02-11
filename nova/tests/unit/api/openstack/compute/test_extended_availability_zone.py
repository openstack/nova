# Copyright 2011 OpenStack Foundation
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

from nova import availability_zones
from nova.compute import vm_states
from nova import exception
from nova import objects
from nova.objects import instance as instance_obj
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance

UUID1 = '00000000-0000-0000-0000-000000000001'
UUID2 = '00000000-0000-0000-0000-000000000002'
UUID3 = '00000000-0000-0000-0000-000000000003'


def fake_compute_get_az(*args, **kwargs):
    inst = fakes.stub_instance(1, uuid=UUID3, host="get-host",
                               vm_state=vm_states.ACTIVE,
                               availability_zone='fakeaz')
    return fake_instance.fake_instance_obj(args[1], **inst)


def fake_compute_get_empty(*args, **kwargs):
    inst = fakes.stub_instance(1, uuid=UUID3, host="",
                               vm_state=vm_states.ACTIVE,
                               availability_zone='fakeaz')
    return fake_instance.fake_instance_obj(args[1], **inst)


def fake_compute_get(*args, **kwargs):
    inst = fakes.stub_instance(1, uuid=UUID3, host="get-host",
                               vm_state=vm_states.ACTIVE)
    return fake_instance.fake_instance_obj(args[1], **inst)


def fake_compute_get_all(*args, **kwargs):
    inst1 = fakes.stub_instance(1, uuid=UUID1, host="all-host",
                                vm_state=vm_states.ACTIVE)
    inst2 = fakes.stub_instance(2, uuid=UUID2, host="all-host",
                                vm_state=vm_states.ACTIVE)
    db_list = [inst1, inst2]
    fields = instance_obj.INSTANCE_DEFAULT_FIELDS
    return instance_obj._make_instance_list(args[1],
                                            objects.InstanceList(),
                                            db_list, fields)


def fake_get_host_availability_zone(context, host):
    return host


def fake_get_no_host_availability_zone(context, host):
    return None


class ExtendedAvailabilityZoneTestV21(test.TestCase):
    content_type = 'application/json'
    prefix = 'OS-EXT-AZ:'
    base_url = '/v2/fake/servers/'

    def setUp(self):
        super(ExtendedAvailabilityZoneTestV21, self).setUp()
        availability_zones.reset_cache()
        fakes.stub_out_nw_api(self)
        fakes.stub_out_secgroup_api(self)
        self.stub_out('nova.compute.api.API.get', fake_compute_get)
        self.stub_out('nova.compute.api.API.get_all', fake_compute_get_all)
        self.stub_out('nova.availability_zones.get_host_availability_zone',
                       fake_get_host_availability_zone)
        return_server = fakes.fake_instance_get()
        self.stub_out('nova.db.api.instance_get_by_uuid', return_server)

    def _make_request(self, url):
        req = fakes.HTTPRequest.blank(url)
        req.headers['Accept'] = self.content_type
        res = req.get_response(fakes.wsgi_app_v21())
        return res

    def _get_server(self, body):
        return jsonutils.loads(body).get('server')

    def _get_servers(self, body):
        return jsonutils.loads(body).get('servers')

    def assertAvailabilityZone(self, server, az):
        self.assertEqual(server.get('%savailability_zone' % self.prefix),
                         az)

    def test_show_no_host_az(self):
        self.stub_out('nova.compute.api.API.get', fake_compute_get_az)
        self.stub_out('nova.availability_zones.get_host_availability_zone',
                      fake_get_no_host_availability_zone)

        url = self.base_url + UUID3
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        self.assertAvailabilityZone(self._get_server(res.body), '')

    def test_show_empty_host_az(self):
        self.stub_out('nova.compute.api.API.get', fake_compute_get_empty)

        url = self.base_url + UUID3
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        self.assertAvailabilityZone(self._get_server(res.body), 'fakeaz')

    def test_show(self):
        url = self.base_url + UUID3
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        self.assertAvailabilityZone(self._get_server(res.body), 'get-host')

    def test_detail(self):
        url = self.base_url + 'detail'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        for i, server in enumerate(self._get_servers(res.body)):
            self.assertAvailabilityZone(server, 'all-host')

    def test_no_instance_passthrough_404(self):

        def fake_compute_get(*args, **kwargs):
            raise exception.InstanceNotFound(instance_id='fake')

        self.stub_out('nova.compute.api.API.get', fake_compute_get)
        url = self.base_url + '70f6db34-de8d-4fbd-aafb-4065bdfa6115'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 404)
