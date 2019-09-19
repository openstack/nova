# Copyright 2019 NTT Corporation
#
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

from nova import context
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit import fake_notifier
from nova.tests.unit.image import fake as fake_image


class RebuildWithKeypairTestCase(
    test.TestCase, integrated_helpers.InstanceHelperMixin,
):
    """Regression test for bug 1843708.

    This tests a rebuild scenario with new key pairs.
    """

    def setUp(self):
        super(RebuildWithKeypairTestCase, self).setUp()
        # Start standard fixtures.
        self.useFixture(func_fixtures.PlacementFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        fake_image.stub_out_image_service(self)
        self.addCleanup(fake_image.FakeImageService_reset)
        fake_notifier.stub_notifier(self)
        self.addCleanup(fake_notifier.reset)
        self.api = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1')).admin_api
        self.api.microversion = 'latest'
        # Start nova services.
        self.start_service('conductor')
        self.start_service('scheduler')
        self.start_service('compute')

    def test_rebuild_with_keypair(self):
        keypair_req = {
            'keypair': {
                'name': 'test-key1',
                'type': 'ssh',
            },
        }
        keypair1 = self.api.post_keypair(keypair_req)
        keypair_req['keypair']['name'] = 'test-key2'
        keypair2 = self.api.post_keypair(keypair_req)

        server = self._build_minimal_create_server_request(
            self.api, 'test-rebuild-with-keypair',
            image_uuid=fake_image.get_valid_image_id(),
            networks='none')
        server.update({'key_name': 'test-key1'})

        # Create a server with keypair 'test-key1'
        server = self.api.post_server({'server': server})
        self._wait_for_state_change(self.api, server, 'ACTIVE')

        # Check keypairs
        ctxt = context.get_admin_context()
        instance = objects.Instance.get_by_uuid(
            ctxt, server['id'], expected_attrs=['keypairs'])
        self.assertEqual(
            keypair1['public_key'], instance.keypairs[0].public_key)

        # Rebuild a server with keypair 'test-key2'
        body = {
            'rebuild': {
                'imageRef': fake_image.get_valid_image_id(),
                'key_name': 'test-key2',
            },
        }
        self.api.api_post('servers/%s/action' % server['id'], body)
        fake_notifier.wait_for_versioned_notifications('instance.rebuild.end')
        self._wait_for_state_change(self.api, server, 'ACTIVE')

        # Check keypairs changed
        instance = objects.Instance.get_by_uuid(
            ctxt, server['id'], expected_attrs=['keypairs'])
        self.assertEqual(
            keypair2['public_key'], instance.keypairs[0].public_key)
