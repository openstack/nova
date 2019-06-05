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

from __future__ import absolute_import

import fixtures
import mock

from nova import context
from nova.network import model as network_model
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures
from nova.tests.unit import cast_as_call
from nova.tests.unit import fake_network
from nova.tests.unit import fake_server_actions


class ComputeManagerTestCase(test.TestCase):
    def setUp(self):
        super(ComputeManagerTestCase, self).setUp()
        self.useFixture(nova_fixtures.SpawnIsSynchronousFixture())
        self.useFixture(cast_as_call.CastAsCall(self))
        self.conductor = self.start_service('conductor')
        self.start_service('scheduler')
        self.compute = self.start_service('compute')
        self.context = context.RequestContext('fake', 'fake')
        fake_server_actions.stub_out_action_events(self)
        fake_network.set_stub_network_methods(self)
        self.useFixture(fixtures.MockPatch(
            'nova.network.base_api.NetworkAPI.get_instance_nw_info',
            return_value=network_model.NetworkInfo(),
        ))

    def test_instance_fault_message_no_traceback_with_retry(self):
        """This test simulates a spawn failure on the last retry attempt.

        If driver spawn raises an exception on the last retry attempt, the
        instance fault message should not contain a traceback for the
        last exception. The fault message field is limited in size and a long
        message with a traceback displaces the original error message.
        """
        self.flags(max_attempts=3, group='scheduler')
        flavor = objects.Flavor(
                id=1, name='flavor1', memory_mb=256, vcpus=1, root_gb=1,
                ephemeral_gb=1, flavorid='1', swap=0, rxtx_factor=1.0,
                vcpu_weight=1, disabled=False, is_public=True, extra_specs={},
                projects=[])
        instance = objects.Instance(self.context, flavor=flavor, vcpus=1,
                                    memory_mb=256, root_gb=0, ephemeral_gb=0,
                                    project_id='fake')
        instance.create()

        # Amongst others, mock the resource tracker, otherwise it will
        # not have been sufficiently initialized and will raise a KeyError
        # on the self.compute_nodes dict after the TestingException.
        @mock.patch.object(self.conductor.manager.compute_task_mgr,
                           '_cleanup_allocated_networks')
        @mock.patch.object(self.compute.manager.network_api,
                           'cleanup_instance_network_on_host')
        @mock.patch('nova.compute.utils.notify_about_instance_usage')
        @mock.patch.object(self.compute.manager, 'rt')
        @mock.patch.object(self.compute.manager.driver, 'spawn')
        def _test(mock_spawn, mock_grt, mock_notify, mock_cinoh, mock_can):
            mock_spawn.side_effect = test.TestingException('Preserve this')
            # Simulate that we're on the last retry attempt
            filter_properties = {'retry': {'num_attempts': 3}}
            request_spec = objects.RequestSpec.from_primitives(
                self.context,
                {'instance_properties': {'uuid': instance.uuid},
                 'instance_type': flavor,
                 'image': None},
                filter_properties)
            self.compute.manager.build_and_run_instance(
                    self.context, instance, {}, request_spec,
                    filter_properties, block_device_mapping=[])
        _test()
        self.assertIn('Preserve this', instance.fault.message)
