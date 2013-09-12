# vim: tabstop=4 shiftwidth=4 softtabstop=4
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
from nova.tests.api.openstack import fakes
from nova.tests.integrated.v3 import test_servers
from nova.volume import cinder


class ExtendedVolumesSampleJsonTests(test_servers.ServersSampleBase):
    extension_name = "os-extended-volumes"

    def _stub_compute_api_get_instance_bdms(self, server_id):

        def fake_compute_api_get_instance_bdms(self, context, instance):
            bdms = [
                {'volume_id': 'a26887c6-c47b-4654-abb5-dfadf7d3f803',
                'instance_uuid': server_id,
                'device_name': '/dev/sdd'},
                {'volume_id': 'a26887c6-c47b-4654-abb5-dfadf7d3f804',
                'instance_uuid': server_id,
                'device_name': '/dev/sdc'}
            ]
            return bdms

        self.stubs.Set(compute_api.API, "get_instance_bdms",
                       fake_compute_api_get_instance_bdms)

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
        self.assertEqual(response.status, 202)
        self.assertEqual(response.read(), '')


class ExtendedVolumesSampleXmlTests(ExtendedVolumesSampleJsonTests):
    ctype = 'xml'
