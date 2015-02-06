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

import mock
from oslo_config import cfg
from oslo_serialization import jsonutils

from nova import test
from nova.tests.unit.api.openstack import fakes

CONF = cfg.CONF


class PluginTest(test.NoDBTestCase):

    @mock.patch("nova.api.openstack.APIRouterV21.api_extension_namespace")
    def test_plugin_framework_index(self, mock_namespace):
        mock_namespace.return_value = 'nova.api.v3.test_extensions'

        app = fakes.wsgi_app_v21(init_only='test-basic')
        req = fakes.HTTPRequest.blank('/v2/fake/test')
        res = req.get_response(app)
        self.assertEqual(200, res.status_int)
        resp_json = jsonutils.loads(res.body)
        self.assertEqual('val', resp_json['param'])
