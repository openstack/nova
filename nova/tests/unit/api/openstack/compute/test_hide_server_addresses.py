# Copyright 2012 OpenStack Foundation
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
import six

from nova.compute import vm_states
from nova import exception
from nova import objects
from nova.objects import instance as instance_obj
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_instance


SENTINEL = object()


def fake_compute_get(*args, **kwargs):
    def _return_server(*_args, **_kwargs):
        inst = fakes.stub_instance(*args, **kwargs)
        return fake_instance.fake_instance_obj(_args[1], **inst)
    return _return_server


class HideServerAddressesTestV21(test.TestCase):
    content_type = 'application/json'
    base_url = '/v2/fake/servers'

    def _setup_wsgi(self):
        self.wsgi_app = fakes.wsgi_app_v21()

    def setUp(self):
        super(HideServerAddressesTestV21, self).setUp()
        fakes.stub_out_nw_api(self)
        fakes.stub_out_secgroup_api(self)
        return_server = fakes.fake_instance_get()
        self.stub_out('nova.db.instance_get_by_uuid', return_server)
        self._setup_wsgi()

    def _make_request(self, url):
        req = fakes.HTTPRequest.blank(url)
        req.headers['Accept'] = self.content_type
        res = req.get_response(self.wsgi_app)
        return res

    @staticmethod
    def _get_server(body):
        return jsonutils.loads(body).get('server')

    @staticmethod
    def _get_servers(body):
        return jsonutils.loads(body).get('servers')

    @staticmethod
    def _get_addresses(server):
        return server.get('addresses', SENTINEL)

    def _check_addresses(self, addresses, exists):
        self.assertIsNot(addresses, SENTINEL)
        if exists:
            self.assertTrue(addresses)
        else:
            self.assertFalse(addresses)

    def test_show_hides_in_building(self):
        instance_id = 1
        uuid = fakes.get_fake_uuid(instance_id)
        self.stub_out('nova.compute.api.API.get',
                      fake_compute_get(instance_id, uuid=uuid,
                                       vm_state=vm_states.BUILDING))
        res = self._make_request(self.base_url + '/%s' % uuid)
        self.assertEqual(200, res.status_int)

        server = self._get_server(res.body)
        addresses = self._get_addresses(server)
        self._check_addresses(addresses, exists=False)

    def test_show(self):
        instance_id = 1
        uuid = fakes.get_fake_uuid(instance_id)
        self.stub_out('nova.compute.api.API.get',
                      fake_compute_get(instance_id, uuid=uuid,
                                       vm_state=vm_states.ACTIVE))
        res = self._make_request(self.base_url + '/%s' % uuid)
        self.assertEqual(200, res.status_int)

        server = self._get_server(res.body)
        addresses = self._get_addresses(server)
        self._check_addresses(addresses, exists=True)

    def test_detail_hides_building_server_addresses(self):
        instance_0 = fakes.stub_instance(0, uuid=fakes.get_fake_uuid(0),
                                         vm_state=vm_states.ACTIVE)
        instance_1 = fakes.stub_instance(1, uuid=fakes.get_fake_uuid(1),
                                         vm_state=vm_states.BUILDING)
        instances = [instance_0, instance_1]

        def get_all(*args, **kwargs):
            fields = instance_obj.INSTANCE_DEFAULT_FIELDS
            return instance_obj._make_instance_list(
                args[1], objects.InstanceList(), instances, fields)

        self.stub_out('nova.compute.api.API.get_all', get_all)
        res = self._make_request(self.base_url + '/detail')

        self.assertEqual(200, res.status_int)
        servers = self._get_servers(res.body)

        self.assertEqual(len(servers), len(instances))

        for instance, server in six.moves.zip(instances, servers):
            addresses = self._get_addresses(server)
            exists = (instance['vm_state'] == vm_states.ACTIVE)
            self._check_addresses(addresses, exists=exists)

    def test_no_instance_passthrough_404(self):

        def fake_compute_get(*args, **kwargs):
            raise exception.InstanceNotFound(instance_id='fake')

        self.stub_out('nova.compute.api.API.get', fake_compute_get)
        res = self._make_request(self.base_url + '/' + fakes.get_fake_uuid())

        self.assertEqual(404, res.status_int)
