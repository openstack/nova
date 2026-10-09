# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Regression test for bug 2164869.

https://bugs.launchpad.net/nova/+bug/2164869

Querying a subpath of a leaf metadata value (e.g.
``/latest/meta-data/security-groups/default``) causes the metadata service
to raise an unhandled ``TypeError`` instead of returning HTTP 404. The root
cause is that ``find_path_in_tree`` tries to index a list with a string key
(``data["default"]`` where data is ``['default']``) and the resulting
``TypeError`` is not caught by the ``except`` clause in
``InstanceMetadata.lookup()``.
"""

import fixtures
import requests

from wsgi_intercept import WSGIAppError

from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers


class TestMetadataLeafSubpathRaisesTypeError(
    test.TestCase, integrated_helpers.InstanceHelperMixin,
):
    """Regression test for bug 2164869.

    see https://bugs.launchpad.net/nova/+bug/2164869 for details.
    """

    def setUp(self):
        super().setUp()
        self.useFixture(nova_fixtures.GlanceFixture(self))
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())
        self.start_service('conductor')
        self.start_service('scheduler')
        self.api = self.useFixture(
            nova_fixtures.OSAPIFixture(api_version='v2.1')).api
        self.start_service('compute')

        server = self._build_server(name='test')
        server = self.api.post_server({'server': server})
        self.server = self._wait_for_state_change(server, 'ACTIVE')

        self.api_fixture = self.useFixture(nova_fixtures.OSMetadataServer())
        self.md_url = self.api_fixture.md_url

        def fake_get_fixed_ip_by_address(self, ctxt, address):
            return {'instance_uuid': server['id']}

        self.useFixture(
            fixtures.MonkeyPatch(
                'nova.network.neutron.API.get_fixed_ip_by_address',
                fake_get_fixed_ip_by_address))

    def test_metadata_leaf_subpath_raises_type_error(self):
        # Verify that querying the leaf value itself works.
        url = '%slatest/meta-data/security-groups' % self.md_url
        res = requests.request('GET', url, timeout=5)
        self.assertEqual(200, res.status_code)
        self.assertIn('default', res.text)

        # TODO(bug #2164869) Querying a subpath of a leaf value should
        # return HTTP 404, but currently raises an unhandled TypeError
        # that propagates out of the WSGI stack. Once the bug is fixed,
        # this should be:
        #   res = requests.request('GET', url, timeout=5)
        #   self.assertEqual(404, res.status_code)
        url = '%slatest/meta-data/security-groups/default' % self.md_url
        self.assertRaises(
            WSGIAppError,
            requests.request, 'GET', url, timeout=5)
