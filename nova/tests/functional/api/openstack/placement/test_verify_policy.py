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

from oslo_config import cfg

from nova.api.openstack.placement import direct
from nova.api.openstack.placement import handler
from nova.tests.functional.api.openstack.placement import base


CONF = cfg.CONF


class TestVerifyPolicy(base.TestCase):
    """Verify that all defined placement routes have a policy."""

    # Paths that don't need a policy check
    EXCEPTIONS = ['/', '']

    def _test_request_403(self, client, method, route):
        headers = {
            'x-auth-token': 'user',
            'content-type': 'application/json'
        }
        request_method = getattr(client, method.lower())
        # We send an empty request body on all requests. Because
        # policy handling comes before other processing, the value
        # of the body is irrelevant.
        response = request_method(route, data='', headers=headers)
        self.assertEqual(
            403, response.status_code,
            'method %s on route %s is open for user, status: %s' %
            (method, route, response.status_code))

    def test_verify_policy(self):
        with direct.PlacementDirect(CONF, latest_microversion=True) as client:
            for route, methods in handler.ROUTE_DECLARATIONS.items():
                if route in self.EXCEPTIONS:
                    continue
                for method in methods:
                    self._test_request_403(client, method, route)
