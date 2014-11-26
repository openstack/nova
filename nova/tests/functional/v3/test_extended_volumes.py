# Copyright 2012 Nebula, Inc.
# Copyright 2013 IBM Corp.
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

from nova.compute import api as compute_api
from nova.compute import manager as compute_manager
from nova import context
from nova import db
from nova import objects
from nova.tests.functional.v3 import test_servers
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_block_device
from nova.tests.unit import fake_instance
from nova.volume import cinder


class ExtendedVolumesSampleJsonTests(test_servers.ServersSampleBase):
    extension_name = "os-extended-volumes"

    def _stub_compute_api_get_instance_bdms(self, server_id):

        def fake_bdms_get_all_by_instance(context, instance_uuid,
                                          use_slave=False):
            bdms = [
                fake_block_device.FakeDbBlockDeviceDict(
                {'id': 1, 'volume_id': 'a26887c6-c47b-4654-abb5-dfadf7d3f803',
                'instance_uuid': server_id, 'source_type': 'volume',
                'destination_type': 'volume', 'device_name': '/dev/sdd'}),
                fake_block_device.FakeDbBlockDeviceDict(
                {'id': 2, 'volume_id': 'a26887c6-c47b-4654-abb5-dfadf7d3f804',
                'instance_uuid': server_id, 'source_type': 'volume',
                'destination_type': 'volume', 'device_name': '/dev/sdc'})
            ]
            return bdms

        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       fake_bdms_get_all_by_instance)

    def _stub_compute_api_get(self):
        def fake_compute_api_get(self, context, instance_id, **kwargs):
            want_objects = kwargs.get('want_objects')
            if want_objects:
                return fake_instance.fake_instance_obj(
                        context, **{'uuid': instance_id})
            else:
                return {'uuid': instance_id}

        self.stubs.Set(compute_api.API, 'get', fake_compute_api_get)

    def test_show(self):
        uuid = self._post_server()
        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       fakes.stub_bdm_get_all_by_instance)
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('server-get-resp', subs, response, 200)

    def test_detail(self):
        uuid = self._post_server()
        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       fakes.stub_bdm_get_all_by_instance)
        response = self._do_get('servers/detail')
        subs = self._get_regexes()
        subs['id'] = uuid
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('servers-detail-resp', subs, response, 200)

    def test_attach_volume(self):
        bdm = objects.BlockDeviceMapping()
        device_name = '/dev/vdd'
        bdm['device_name'] = device_name
        self.stubs.Set(cinder.API, 'get', fakes.stub_volume_get)
        self.stubs.Set(cinder.API, 'check_attach', lambda *a, **k: None)
        self.stubs.Set(cinder.API, 'reserve_volume', lambda *a, **k: None)
        self.stubs.Set(compute_manager.ComputeManager,
                       "reserve_block_device_name",
                       lambda *a, **k: bdm)
        self.stubs.Set(compute_manager.ComputeManager,
                       'attach_volume',
                       lambda *a, **k: None)

        volume = fakes.stub_volume_get(None, context.get_admin_context(),
                                       'a26887c6-c47b-4654-abb5-dfadf7d3f803')
        subs = {
            'volume_id': volume['id'],
            'device': device_name,
            'disk_bus': 'ide',
            'device_type': 'cdrom'
        }
        server_id = self._post_server()
        response = self._do_post('servers/%s/action'
                                 % server_id,
                                 'attach-volume-req', subs)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')

    def test_detach_volume(self):
        server_id = self._post_server()
        attach_id = "a26887c6-c47b-4654-abb5-dfadf7d3f803"
        self._stub_compute_api_get_instance_bdms(server_id)
        self._stub_compute_api_get()
        self.stubs.Set(cinder.API, 'get', fakes.stub_volume_get)
        self.stubs.Set(compute_api.API, 'detach_volume', lambda *a, **k: None)
        subs = {
            'volume_id': attach_id,
        }
        response = self._do_post('servers/%s/action'
                                 % server_id, 'detach-volume-req', subs)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')

    def test_swap_volume(self):
        server_id = self._post_server()
        old_volume_id = "a26887c6-c47b-4654-abb5-dfadf7d3f803"
        old_new_volume = 'a26887c6-c47b-4654-abb5-dfadf7d3f805'
        self._stub_compute_api_get_instance_bdms(server_id)

        def stub_volume_get(self, context, volume_id):
            if volume_id == old_volume_id:
                return fakes.stub_volume(volume_id, instance_uuid=server_id)
            else:
                return fakes.stub_volume(volume_id, instance_uuid=None,
                                         attach_status='detached')

        self.stubs.Set(cinder.API, 'get', stub_volume_get)
        self.stubs.Set(cinder.API, 'begin_detaching', lambda *a, **k: None)
        self.stubs.Set(cinder.API, 'check_attach', lambda *a, **k: None)
        self.stubs.Set(cinder.API, 'check_detach', lambda *a, **k: None)
        self.stubs.Set(cinder.API, 'reserve_volume', lambda *a, **k: None)
        self.stubs.Set(compute_manager.ComputeManager, 'swap_volume',
                       lambda *a, **k: None)
        subs = {
            'old_volume_id': old_volume_id,
            'new_volume_id': old_new_volume
        }
        response = self._do_post('servers/%s/action' % server_id,
                                 'swap-volume-req', subs)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')
