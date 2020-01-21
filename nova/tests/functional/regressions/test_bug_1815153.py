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

from nova.compute import instance_actions
from nova import context
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.functional import fixtures as func_fixtures
from nova.tests.functional import integrated_helpers
from nova.tests.unit.image import fake as image_fake
from nova.tests.unit import policy_fixture


class NonPersistentFieldNotResetTest(
        test.TestCase, integrated_helpers.InstanceHelperMixin):
    """Test for regression bug 1815153

    The bug is that the 'requested_destination' field in the RequestSpec
    object is reset when saving the object in the 'heal_reqspec_is_bfv'
    method in the case that a server created before Rocky which does not
    have is_bfv field.

    Tests the following two cases here.

    * Cold migration with a target host without a force flag
    * Evacuate with a target host without a force flag

    The following two cases are not tested here because
    'requested_destination' is not set when the 'heal_reqspec_is_bfv' method
    is called.

    * Live migration without a destination host.
    * Unshelve a server
    """

    def setUp(self):
        super(NonPersistentFieldNotResetTest, self).setUp()
        self.useFixture(policy_fixture.RealPolicyFixture())
        self.useFixture(nova_fixtures.NeutronFixture(self))
        self.useFixture(func_fixtures.PlacementFixture())

        api_fixture = self.useFixture(nova_fixtures.OSAPIFixture(
            api_version='v2.1'))
        self.api = api_fixture.admin_api
        # Use the latest microversion available to make sure something does
        # not regress in new microversions; cap as necessary.
        self.api.microversion = 'latest'

        image_fake.stub_out_image_service(self)
        self.addCleanup(image_fake.FakeImageService_reset)

        self.start_service('conductor')
        self.start_service('scheduler')

        self.compute = {}

        for host in ('host1', 'host2', 'host3'):
            compute_service = self.start_service('compute', host=host)
            self.compute.update({host: compute_service})

        self.ctxt = context.get_admin_context()

    @staticmethod
    def _get_target_host(host):
        target_host = {'host1': 'host2',
                       'host2': 'host3',
                       'host3': 'host1'}
        return target_host[host]

    def _remove_is_bfv_in_request_spec(self, server_id):
        # Now let's hack the RequestSpec.is_bfv field to mimic migrating an
        # old instance created before RequestSpec.is_bfv was set in the API,
        reqspec = objects.RequestSpec.get_by_instance_uuid(self.ctxt,
                                                           server_id)
        del reqspec.is_bfv
        reqspec.save()
        reqspec = objects.RequestSpec.get_by_instance_uuid(self.ctxt,
                                                           server_id)
        # Make sure 'is_bfv' is not set.
        self.assertNotIn('is_bfv', reqspec)

    def test_cold_migrate(self):
        server = self._create_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            networks='none')
        original_host = server['OS-EXT-SRV-ATTR:host']
        target_host = self._get_target_host(original_host)
        self._remove_is_bfv_in_request_spec(server['id'])

        # Force a target host down
        source_compute_id = self.api.get_services(
            host=target_host, binary='nova-compute')[0]['id']
        self.compute[target_host].stop()
        self.api.put_service(
            source_compute_id, {'forced_down': 'true'})

        # Cold migrate a server with a target host.
        # The response status code is 202 even though the operation will
        # fail because the requested target host is down which will result
        # in a NoValidHost error.
        self.api.post_server_action(
            server['id'], {'migrate': {'host': target_host}},
            check_response_status=[202])
        # The instance action should have failed with details.
        self._assert_resize_migrate_action_fail(
            server, instance_actions.MIGRATE, 'NoValidHost')

        # Make sure 'is_bfv' is set.
        reqspec = objects.RequestSpec.get_by_instance_uuid(self.ctxt,
                                                           server['id'])
        self.assertIn('is_bfv', reqspec)
        self.assertIs(reqspec.is_bfv, False)

    def test_evacuate(self):
        server = self._create_server(
            image_uuid='155d900f-4e14-4e4c-a73d-069cbf4541e6',
            networks='none')
        original_host = server['OS-EXT-SRV-ATTR:host']
        target_host = self._get_target_host(original_host)
        self._remove_is_bfv_in_request_spec(server['id'])

        # Force source and target hosts down
        for host in (original_host, target_host):
            source_compute_id = self.api.get_services(
                host=host, binary='nova-compute')[0]['id']
            self.compute[host].stop()
            self.api.put_service(
                source_compute_id, {'forced_down': 'true'})

        # Evacuate a server with a target host.
        # If requested_destination is reset, the server is moved to a host
        # that is not the target host.
        # Its status becomes 'ACTIVE'.
        # If requested_destination is not reset, a status of the server
        # becomes 'ERROR' because the target host is down.
        self.api.post_server_action(
            server['id'], {'evacuate': {'host': target_host}})
        expected_params = {'OS-EXT-SRV-ATTR:host': original_host,
                           'status': 'ERROR'}
        server = self._wait_for_server_parameter(server, expected_params)

        # Make sure 'is_bfv' is set.
        reqspec = objects.RequestSpec.get_by_instance_uuid(self.ctxt,
                                                           server['id'])
        self.assertIn('is_bfv', reqspec)
        self.assertIs(reqspec.is_bfv, False)
