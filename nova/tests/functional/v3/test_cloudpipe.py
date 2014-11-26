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

import uuid as uuid_lib

from oslo.config import cfg

from nova.cloudpipe import pipelib
from nova.network import api as network_api
from nova.tests.functional.v3 import api_sample_base
from nova.tests.unit.image import fake


CONF = cfg.CONF
CONF.import_opt('vpn_image_id', 'nova.cloudpipe.pipelib')


class CloudPipeSampleTest(api_sample_base.ApiSampleTestBaseV3):
    extension_name = "os-cloudpipe"

    def setUp(self):
        super(CloudPipeSampleTest, self).setUp()

        def get_user_data(self, project_id):
            """Stub method to generate user data for cloudpipe tests."""
            return "VVNFUiBEQVRB\n"

        def network_api_get(self, context, network_uuid):
            """Stub to get a valid network and its information."""
            return {'vpn_public_address': '127.0.0.1',
                    'vpn_public_port': 22}

        self.stubs.Set(pipelib.CloudPipe, 'get_encoded_zip', get_user_data)
        self.stubs.Set(network_api.API, "get",
                       network_api_get)

    def generalize_subs(self, subs, vanilla_regexes):
        subs['project_id'] = '[0-9a-f-]+'
        return subs

    def test_cloud_pipe_create(self):
        # Get api samples of cloud pipe extension creation.
        self.flags(vpn_image_id=fake.get_valid_image_id())
        project = {'project_id': str(uuid_lib.uuid4().hex)}
        response = self._do_post('os-cloudpipe', 'cloud-pipe-create-req',
                                 project)
        subs = self._get_regexes()
        subs.update(project)
        subs['image_id'] = CONF.vpn_image_id
        self._verify_response('cloud-pipe-create-resp', subs, response, 200)
        return project

    def test_cloud_pipe_list(self):
        # Get api samples of cloud pipe extension get request.
        project = self.test_cloud_pipe_create()
        response = self._do_get('os-cloudpipe')
        subs = self._get_regexes()
        subs.update(project)
        subs['image_id'] = CONF.vpn_image_id
        self._verify_response('cloud-pipe-get-resp', subs, response, 200)

    def test_cloud_pipe_update(self):
        subs = {'vpn_ip': '192.168.1.1',
                'vpn_port': 2000}
        response = self._do_put('os-cloudpipe/configure-project',
                                'cloud-pipe-update-req',
                                subs)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, "")
