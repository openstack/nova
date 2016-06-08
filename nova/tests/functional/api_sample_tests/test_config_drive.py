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

from nova.tests.functional.api_sample_tests import test_servers
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.image import fake


class ConfigDriveSampleJsonTest(test_servers.ServersSampleBase):
    extension_name = 'os-config-drive'

    def setUp(self):
        super(ConfigDriveSampleJsonTest, self).setUp()
        fakes.stub_out_networking(self)
        fake.stub_out_image_service(self)

    def test_config_drive_show(self):
        uuid = self._post_server(use_common_server_api_samples=False)
        response = self._do_get('servers/%s' % uuid)
        subs = {}
        subs['hostid'] = '[a-f0-9]+'
        # config drive can be a string for True or empty value for False
        subs['cdrive'] = '.*'
        subs['access_ip_v4'] = '1.2.3.4'
        subs['access_ip_v6'] = '80fe::'
        self._verify_response('server-config-drive-get-resp', subs,
                              response, 200)

    def test_config_drive_detail(self):
        self._post_server(use_common_server_api_samples=False)
        response = self._do_get('servers/detail')
        subs = {}
        subs['hostid'] = '[a-f0-9]+'
        # config drive can be a string for True or empty value for False
        subs['cdrive'] = '.*'
        subs['access_ip_v4'] = '1.2.3.4'
        subs['access_ip_v6'] = '80fe::'
        self._verify_response('servers-config-drive-details-resp',
                              subs, response, 200)
