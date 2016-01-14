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

from oslo_utils import importutils

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
CONF.import_opt('compute_manager', 'nova.service')


class ComputeXenTestCase(stubs.XenAPITestBaseNoDB):
    def setUp(self):
        super(ComputeXenTestCase, self).setUp()
        self.flags(compute_driver='xenapi.XenAPIDriver')
        self.flags(connection_url='test_url',
                   connection_password='test_pass',
                   group='xenserver')

        stubs.stubout_session(self.stubs, stubs.FakeSessionForVMTests)
        self.compute = importutils.import_object(CONF.compute_manager)
        # execute power syncing synchronously for testing:
        self.compute._sync_power_pool = eventlet_utils.SyncPool()

    def test_sync_power_states_instance_not_found(self):
        db_instance = fake_instance.fake_db_instance()
        ctxt = context.get_admin_context()
        instance_list = instance_obj._make_instance_list(ctxt,
                objects.InstanceList(), [db_instance], None)
        instance = instance_list[0]

        self.mox.StubOutWithMock(objects.InstanceList, 'get_by_host')
        self.mox.StubOutWithMock(self.compute.driver, 'get_num_instances')
        self.mox.StubOutWithMock(vm_utils, 'lookup')
        self.mox.StubOutWithMock(self.compute, '_sync_instance_power_state')

        objects.InstanceList.get_by_host(ctxt,
                self.compute.host, expected_attrs=[],
                use_slave=True).AndReturn(instance_list)
        self.compute.driver.get_num_instances().AndReturn(1)
        vm_utils.lookup(self.compute.driver._session, instance['name'],
                False).AndReturn(None)
        self.compute._sync_instance_power_state(ctxt, instance,
                power_state.NOSTATE)

        self.mox.ReplayAll()

        self.compute._sync_power_states(ctxt)
