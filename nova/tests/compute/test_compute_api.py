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

"""Unit tests for compute API."""

from nova.compute import api as compute_api
from nova.compute import cells_api as compute_cells_api
from nova.compute import flavors
from nova.compute import instance_actions
from nova.compute import task_states
from nova.compute import vm_states
from nova import context
from nova import exception
from nova.objects import base as obj_base
from nova.objects import instance as instance_obj
from nova.openstack.common import timeutils
from nova.openstack.common import uuidutils
from nova import test


FAKE_IMAGE_REF = 'fake-image-ref'
NODENAME = 'fakenode1'


class _ComputeAPIUnitTestMixIn(object):
    def setUp(self):
        super(_ComputeAPIUnitTestMixIn, self).setUp()
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id,
                                              self.project_id)

    def _create_flavor(self, params=None):
        flavor = {'id': 1,
                  'flavorid': 1,
                  'name': 'm1.tiny',
                  'memory_mb': 512,
                  'vcpus': 1,
                  'vcpu_weight': None,
                  'root_gb': 1,
                  'ephemeral_gb': 0,
                  'rxtx_factor': 1,
                  'swap': 0,
                  'deleted': 0,
                  'disabled': False,
                  'is_public': True,
                 }
        if params:
            flavor.update(params)
        return flavor

    def _create_instance_obj(self, params=None, flavor=None):
        """Create a test instance."""
        if not params:
            params = {}

        if flavor is None:
            flavor = self._create_flavor()

        def make_fake_sys_meta():
            sys_meta = {}
            for key in flavors.system_metadata_flavor_props:
                sys_meta['instance_type_%s' % key] = flavor[key]
            return sys_meta

        now = timeutils.utcnow()

        instance = instance_obj.Instance()
        instance.id = 1
        instance.uuid = uuidutils.generate_uuid()
        instance.cell_name = 'api!child'
        instance.vm_state = vm_states.ACTIVE
        instance.task_state = None
        instance.image_ref = FAKE_IMAGE_REF
        instance.reservation_id = 'r-fakeres'
        instance.user_id = self.user_id
        instance.project_id = self.project_id
        instance.host = 'fake_host'
        instance.node = NODENAME
        instance.instance_type_id = flavor['id']
        instance.ami_launch_index = 0
        instance.memory_mb = 0
        instance.vcpus = 0
        instance.root_gb = 0
        instance.ephemeral_gb = 0
        instance.architecture = 'x86_64'
        instance.os_type = 'Linux'
        instance.system_metadata = make_fake_sys_meta()
        instance.locked = False
        instance.created_at = now
        instance.updated_at = now
        instance.launched_at = now

        if params:
            instance.update(params)
        instance.obj_reset_changes()
        return instance

    def test_start(self):
        params = dict(vm_state=vm_states.STOPPED)
        instance = self._create_instance_obj(params=params)

        self.mox.StubOutWithMock(instance, 'save')
        self.mox.StubOutWithMock(self.compute_api,
                '_record_action_start')
        self.mox.StubOutWithMock(
                self.compute_api.compute_rpcapi,
                'start_instance')

        instance.save(expected_task_state=None)
        self.compute_api._record_action_start(self.context,
                instance, instance_actions.START)
        self.compute_api.compute_rpcapi.start_instance(
                self.context, instance)

        if self.is_cells:
            self.mox.StubOutWithMock(self.compute_api.cells_rpcapi,
                                     'start_instance')
            self.compute_api.cells_rpcapi.start_instance(
                    self.context, instance)

        self.mox.ReplayAll()

        self.compute_api.start(self.context, instance)
        self.assertEqual(task_states.POWERING_ON,
                         instance.task_state)

    def test_start_invalid_state(self):
        instance = self._create_instance_obj()
        self.assertEqual(instance.vm_state, vm_states.ACTIVE)
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.start,
                          self.context, instance)

    def test_start_no_host(self):
        params = dict(vm_state=vm_states.STOPPED, host='')
        instance = self._create_instance_obj(params=params)
        self.assertRaises(exception.InstanceNotReady,
                          self.compute_api.start,
                          self.context, instance)

    def test_stop(self):
        # Make sure 'progress' gets reset
        params = dict(task_state=None, progress=99)
        instance = self._create_instance_obj(params=params)

        self.mox.StubOutWithMock(instance, 'save')
        self.mox.StubOutWithMock(self.compute_api,
                '_record_action_start')
        self.mox.StubOutWithMock(
                self.compute_api.compute_rpcapi,
                'stop_instance')

        instance.save(expected_task_state=None)
        self.compute_api._record_action_start(self.context,
                instance, instance_actions.STOP)
        self.compute_api.compute_rpcapi.stop_instance(
                self.context, instance, cast=True)

        if self.is_cells:
            self.mox.StubOutWithMock(self.compute_api.cells_rpcapi,
                                     'stop_instance')
            self.compute_api.cells_rpcapi.stop_instance(
                    self.context, instance, do_cast=True)

        self.mox.ReplayAll()

        self.compute_api.stop(self.context, instance)
        self.assertEqual(task_states.POWERING_OFF,
                         instance.task_state)
        self.assertEqual(0, instance.progress)

    def test_stop_invalid_state(self):
        params = dict(vm_state=vm_states.PAUSED)
        instance = self._create_instance_obj(params=params)
        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.stop,
                          self.context, instance)

    def test_stop_a_stopped_inst(self):
        params = {'vm_state': vm_states.STOPPED}
        instance = self._create_instance_obj(params=params)

        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.stop,
                          self.context, instance)

    def test_stop_no_host(self):
        params = {'host': ''}
        instance = self._create_instance_obj(params=params)
        self.assertRaises(exception.InstanceNotReady,
                          self.compute_api.stop,
                          self.context, instance)

    def _test_reboot_type(self, vm_state, reboot_type, task_state=None):
        # Ensure instance can be soft rebooted.
        inst = self._create_instance_obj()
        inst.vm_state = vm_state
        inst.task_state = task_state
        db_inst = obj_base.obj_to_primitive(inst)

        new_state = (reboot_type == 'HARD' and
                     task_states.REBOOTING_HARD or task_states.REBOOTING)
        new_inst = dict(db_inst, task_state=new_state)

        self.mox.StubOutWithMock(self.context, 'elevated')
        self.mox.StubOutWithMock(self.compute_api, '_get_block_device_info')
        self.mox.StubOutWithMock(self.compute_api, '_record_action_start')
        self.mox.StubOutWithMock(self.compute_api, 'update')
        self.mox.StubOutWithMock(self.compute_api.compute_rpcapi,
                                 'reboot_instance')
        self.compute_api.update(self.context, db_inst,
                                task_state=new_state,
                                expected_task_state=[None,
                                                     task_states.REBOOTING]
                                ).AndReturn(new_inst)
        self.context.elevated().AndReturn(self.context)
        self.compute_api._get_block_device_info(self.context, inst.uuid
                                                ).AndReturn('blkinfo')
        self.compute_api._record_action_start(self.context, new_inst,
                                              instance_actions.REBOOT)
        self.compute_api.compute_rpcapi.reboot_instance(
            self.context, instance=new_inst, block_device_info='blkinfo',
            reboot_type=reboot_type)
        if self.is_cells:
            self.mox.StubOutWithMock(self.compute_api, '_cast_to_cells')
            self.compute_api._cast_to_cells(
                self.context, db_inst, 'reboot', reboot_type)
        self.mox.ReplayAll()

        self.compute_api.reboot(self.context, db_inst, reboot_type)

    def _test_reboot_type_fails(self, reboot_type, **updates):
        inst = self._create_instance_obj()
        inst.update(updates)
        db_inst = obj_base.obj_to_primitive(inst)

        self.assertRaises(exception.InstanceInvalidState,
                          self.compute_api.reboot,
                          self.context, db_inst, reboot_type)

    def test_reboot_hard_active(self):
        self._test_reboot_type(vm_states.ACTIVE, 'HARD')

    def test_reboot_hard_error(self):
        self._test_reboot_type(vm_states.ERROR, 'HARD')

    def test_reboot_hard_rebooting(self):
        self._test_reboot_type(vm_states.ACTIVE, 'HARD',
                               task_state=task_states.REBOOTING)

    def test_reboot_hard_rescued(self):
        self._test_reboot_type_fails('HARD', vm_state=vm_states.RESCUED)

    def test_reboot_hard_error_not_launched(self):
        self._test_reboot_type_fails('HARD', vm_state=vm_states.ERROR,
                                     launched_at=None)

    def test_reboot_soft(self):
        self._test_reboot_type(vm_states.ACTIVE, 'SOFT')

    def test_reboot_soft_error(self):
        self._test_reboot_type(vm_states.ERROR, 'SOFT')

    def test_reboot_soft_rebooting(self):
        self._test_reboot_type_fails('SOFT', task_state=task_states.REBOOTING)

    def test_reboot_soft_rescued(self):
        self._test_reboot_type_fails('SOFT', vm_state=vm_states.RESCUED)

    def test_reboot_soft_error_not_launched(self):
        self._test_reboot_type_fails('SOFT', vm_state=vm_states.ERROR,
                                     launched_at=None)


class ComputeAPIUnitTestCase(_ComputeAPIUnitTestMixIn, test.NoDBTestCase):
    def setUp(self):
        super(ComputeAPIUnitTestCase, self).setUp()
        self.compute_api = compute_api.API()
        self.is_cells = False


class ComputeCellsAPIUnitTestCase(_ComputeAPIUnitTestMixIn, test.NoDBTestCase):
    def setUp(self):
        super(ComputeCellsAPIUnitTestCase, self).setUp()
        self.compute_api = compute_cells_api.ComputeCellsAPI()
        self.is_cells = True
