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

"""Tests for expectations of behaviour from the Xen driver."""

import mock

from nova.compute import manager
from nova.compute import power_state
import nova.conf
from nova import context
from nova import objects
from nova.objects import instance as instance_obj
from nova.tests.unit.compute import eventlet_utils
from nova.tests.unit import fake_instance
from nova.tests.unit.virt.xenapi import stubs
from nova.virt.xenapi import vm_utils

CONF = nova.conf.CONF


class ComputeXenTestCase(stubs.XenAPITestBaseNoDB):
    def setUp(self):
        super(ComputeXenTestCase, self).setUp()
        self.flags(compute_driver='xenapi.XenAPIDriver')
        self.flags(connection_url='http://localhost',
                   connection_password='test_pass',
                   group='xenserver')

        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        self.compute = manager.ComputeManager()
        # execute power syncing synchronously for testing:
        self.compute._sync_power_pool = eventlet_utils.SyncPool()

    def test_sync_power_states_instance_not_found(self):
        db_instance = fake_instance.fake_db_instance()
        ctxt = context.get_admin_context()
        instance_list = instance_obj._make_instance_list(ctxt,
                objects.InstanceList(), [db_instance], None)
        instance = instance_list[0]

        @mock.patch.object(vm_utils, 'lookup')
        @mock.patch.object(objects.InstanceList, 'get_by_host')
        @mock.patch.object(self.compute.driver, 'get_num_instances')
        @mock.patch.object(self.compute, '_sync_instance_power_state')
        def do_test(mock_compute_sync_powerstate,
              mock_compute_get_num_instances,
              mock_instance_list_get_by_host,
              mock_vm_utils_lookup):
            mock_instance_list_get_by_host.return_value = instance_list
            mock_compute_get_num_instances.return_value = 1
            mock_vm_utils_lookup.return_value = None

            self.compute._sync_power_states(ctxt)

            mock_instance_list_get_by_host.assert_called_once_with(
               ctxt, self.compute.host, expected_attrs=[], use_slave=True)
            mock_compute_get_num_instances.assert_called_once_with()
            mock_compute_sync_powerstate.assert_called_once_with(
               ctxt, instance, power_state.NOSTATE, use_slave=True)
            mock_vm_utils_lookup.assert_called_once_with(
               self.compute.driver._session, instance['name'],
               False)

        do_test()
