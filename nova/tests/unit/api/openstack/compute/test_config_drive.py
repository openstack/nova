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

import mock
from oslo_serialization import jsonutils

from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.image import fake
from nova.tests import uuidsentinel as uuids


class ConfigDriveTestV21(test.TestCase):
    base_url = '/v2/fake/servers/'

    def _setup_wsgi(self):
        self.app = fakes.wsgi_app_v21()

    def setUp(self):
        super(ConfigDriveTestV21, self).setUp()
        fakes.stub_out_networking(self)
        fake.stub_out_image_service(self)
        fakes.stub_out_secgroup_api(self)
        self._setup_wsgi()

    def test_show(self):
        self.stub_out('nova.db.api.instance_get',
                      fakes.fake_instance_get())
        self.stub_out('nova.db.api.instance_get_by_uuid',
                      fakes.fake_instance_get())
        # NOTE(sdague): because of the way extensions work, we have to
        # also stub out the Request compute cache with a real compute
        # object. Delete this once we remove all the gorp of
        # extensions modifying the server objects.
        self.stub_out('nova.api.openstack.wsgi.Request.get_db_instance',
                      fakes.fake_compute_get())
        req = fakes.HTTPRequest.blank(self.base_url + uuids.sentinel)
        req.headers['Content-Type'] = 'application/json'
        response = req.get_response(self.app)
        self.assertEqual(response.status_int, 200)
        res_dict = jsonutils.loads(response.body)
        self.assertIn('config_drive', res_dict['server'])

    @mock.patch('nova.compute.api.API.get_all')
    def test_detail_servers(self, mock_get_all):
        # NOTE(danms): Orphan these fakes (no context) so that we
        # are sure that the API is requesting what it needs without
        # having to lazy-load.
        mock_get_all.return_value = objects.InstanceList(
            objects=[fakes.stub_instance_obj(ctxt=None, id=1),
                     fakes.stub_instance_obj(ctxt=None, id=2)])
        req = fakes.HTTPRequest.blank(self.base_url + 'detail')
        res = req.get_response(self.app)
        server_dicts = jsonutils.loads(res.body)['servers']
        self.assertNotEqual(len(server_dicts), 0)
        for server_dict in server_dicts:
            self.assertIn('config_drive', server_dict)
