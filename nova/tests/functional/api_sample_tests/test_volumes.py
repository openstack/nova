# Copyright 2012 Nebula, Inc.
# Copyright 2014 IBM Corp.
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

from oslo_utils.fixture import uuidsentinel as uuids

from nova.tests.functional.api_sample_tests import test_servers
from nova.tests.unit.api.openstack import fakes


class VolumesSampleJsonTest(test_servers.ServersSampleBase):
    sample_dir = "os-volumes"

    def setUp(self):
        super().setUp()
        fakes.stub_out_networking(self)

        self.stub_out(
            "nova.volume.cinder.API.delete", fakes.stub_volume_delete)
        self.stub_out("nova.volume.cinder.API.get", fakes.stub_volume_get)
        self.stub_out(
            "nova.volume.cinder.API.get_all", fakes.stub_volume_get_all)
        self.stub_out(
            "nova.volume.cinder.API.create", fakes.stub_volume_create)

    def _post_volume(self):
        subs_req = {
            'volume_name': "Volume Name",
            'volume_desc': "Volume Description",
        }

        response = self._do_post('os-volumes', 'os-volumes-post-req',
                                 subs_req)
        self._verify_response('os-volumes-post-resp', subs_req, response, 200)

    def test_volumes_show(self):
        subs = {
            'volume_name': "Volume Name",
            'volume_desc': "Volume Description",
        }
        response = self._do_get(f'os-volumes/{uuids.volume}')
        self._verify_response('os-volumes-get-resp', subs, response, 200)

    def test_volumes_index(self):
        subs = {
            'volume_name': "Volume Name",
            'volume_desc': "Volume Description",
        }
        response = self._do_get('os-volumes')
        self._verify_response('os-volumes-index-resp', subs, response, 200)

    def test_volumes_detail(self):
        # For now, index and detail are the same.
        # See the volumes api
        subs = {
            'volume_name': "Volume Name",
            'volume_desc': "Volume Description",
        }
        response = self._do_get('os-volumes/detail')
        self._verify_response('os-volumes-detail-resp', subs, response, 200)

    def test_volumes_create(self):
        self._post_volume()

    def test_volumes_delete(self):
        self._post_volume()
        response = self._do_delete(f'os-volumes/{uuids.volume}')
        self.assertEqual(202, response.status_code)
        self.assertEqual('', response.text)
