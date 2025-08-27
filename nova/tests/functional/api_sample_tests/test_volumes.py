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

import datetime

from nova.tests.functional.api_sample_tests import test_servers
from nova.tests.unit.api.openstack import fakes


def _get_volume_id():
    return 'a26887c6-c47b-4654-abb5-dfadf7d3f803'


def _stub_volume(id, displayname="Volume Name",
                 displaydesc="Volume Description", size=100):
    volume = {
              'id': id,
              'size': size,
              'availability_zone': 'zone1:host1',
              'status': 'in-use',
              'attach_status': 'attached',
              'name': 'vol name',
              'display_name': displayname,
              'display_description': displaydesc,
              'created_at': datetime.datetime(2008, 12, 1, 11, 1, 55),
              'snapshot_id': None,
              'volume_type_id': 'fakevoltype',
              'volume_metadata': [],
              'volume_type': {'name': 'Backup'},
              'multiattach': False,
              'attachments': {'3912f2b4-c5ba-4aec-9165-872876fe202e':
                              {'mountpoint': '/',
                               'attachment_id':
                                   'a26887c6-c47b-4654-abb5-dfadf7d3f803'
                               }
                              }
              }
    return volume


def _stub_volume_get(stub_self, context, volume_id):
    return _stub_volume(volume_id)


def _stub_volume_delete(stub_self, context, *args, **param):
    pass


def _stub_volume_get_all(stub_self, context, search_opts=None):
    id = _get_volume_id()
    return [_stub_volume(id)]


def _stub_volume_create(stub_self, context, size, name, description,
                        snapshot, **param):
    id = _get_volume_id()
    return _stub_volume(id)


class VolumesSampleJsonTest(test_servers.ServersSampleBase):
    sample_dir = "os-volumes"

    def setUp(self):
        super().setUp()
        fakes.stub_out_networking(self)

        self.stub_out("nova.volume.cinder.API.delete",
                      _stub_volume_delete)
        self.stub_out("nova.volume.cinder.API.get", _stub_volume_get)
        self.stub_out("nova.volume.cinder.API.get_all",
                      _stub_volume_get_all)

    def _post_volume(self):
        subs_req = {
                'volume_name': "Volume Name",
                'volume_desc': "Volume Description",
        }

        self.stub_out("nova.volume.cinder.API.create",
                      _stub_volume_create)
        response = self._do_post('os-volumes', 'os-volumes-post-req',
                                 subs_req)
        self._verify_response('os-volumes-post-resp', subs_req, response, 200)

    def test_volumes_show(self):
        subs = {
                'volume_name': "Volume Name",
                'volume_desc': "Volume Description",
        }
        vol_id = _get_volume_id()
        response = self._do_get('os-volumes/%s' % vol_id)
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
        vol_id = _get_volume_id()
        response = self._do_delete('os-volumes/%s' % vol_id)
        self.assertEqual(202, response.status_code)
        self.assertEqual('', response.text)
