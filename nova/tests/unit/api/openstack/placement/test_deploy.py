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
"""Unit tests for the deply function used to build the Placement service."""

from oslo_config import cfg
import webob

from nova.api.openstack.placement import deploy
from nova import test


CONF = cfg.CONF


class DeployTest(test.NoDBTestCase):

    def test_auth_middleware_factory(self):
        """Make sure that configuration settings make their way to
        the keystone middleware correctly.
        """
        auth_uri = 'http://example.com/identity'
        authenticate_header_value = "Keystone uri='%s'" % auth_uri
        self.flags(auth_uri=auth_uri, group='keystone_authtoken')
        # ensure that the auth_token middleware is chosen
        self.flags(auth_strategy='keystone', group='api')
        app = deploy.deploy(CONF, 'nova')
        req = webob.Request.blank('/resource_providers', method="GET")

        response = req.get_response(app)

        self.assertEqual(authenticate_header_value,
                         response.headers['www-authenticate'])
