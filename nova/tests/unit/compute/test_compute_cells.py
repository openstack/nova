# Copyright (c) 2012 Rackspace Hosting
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
"""
Tests For Compute w/ Cells
"""
import functools
import inspect

import mock
from oslo.config import cfg
from oslo.utils import timeutils

from nova.cells import manager
from nova.compute import api as compute_api
from nova.compute import cells_api as compute_cells_api
from nova.compute import delete_types
from nova.compute import flavors
from nova.compute import vm_states
from nova import context
from nova import db
from nova import objects
from nova import quota
from nova import test
from nova.tests.unit.compute import test_compute
from nova.tests.unit import fake_instance
from nova.tests.unit.objects import test_flavor


ORIG_COMPUTE_API = None
cfg.CONF.import_opt('enable', 'nova.cells.opts', group='cells')


def stub_call_to_cells(context, instance, method, *args, **kwargs):
    fn = getattr(ORIG_COMPUTE_API, method)
    original_instance = kwargs.pop('original_instance', None)
    if original_instance:
        instance = original_instance
        # Restore this in 'child cell DB'
        db.instance_update(context, instance['uuid'],
                dict(vm_state=instance['vm_state'],
                     task_state=instance['task_state']))

    # Use NoopQuotaDriver in child cells.
    saved_quotas = quota.QUOTAS
    quota.QUOTAS = quota.QuotaEngine(
            quota_driver_class=quota.NoopQuotaDriver())
    compute_api.QUOTAS = quota.QUOTAS
    try:
        return fn(context, instance, *args, **kwargs)
    finally:
        quota.QUOTAS = saved_quotas
        compute_api.QUOTAS = saved_quotas


def stub_cast_to_cells(context, instance, method, *args, **kwargs):
    fn = getattr(ORIG_COMPUTE_API, method)
    original_instance = kwargs.pop('original_instance', None)
    if original_instance:
        instance = original_instance
        # Restore this in 'child cell DB'
        db.instance_update(context, instance['uuid'],
                dict(vm_state=instance['vm_state'],
                     task_state=instance['task_state']))

    # Use NoopQuotaDriver in child cells.
    saved_quotas = quota.QUOTAS
    quota.QUOTAS = quota.QuotaEngine(
            quota_driver_class=quota.NoopQuotaDriver())
    compute_api.QUOTAS = quota.QUOTAS
    try:
        fn(context, instance, *args, **kwargs)
    finally:
        quota.QUOTAS = saved_quotas
        compute_api.QUOTAS = saved_quotas


def deploy_stubs(stubs, api, original_instance=None):
    call = stub_call_to_cells
    cast = stub_cast_to_cells

    if original_instance:
        kwargs = dict(original_instance=original_instance)
        call = functools.partial(stub_call_to_cells, **kwargs)
        cast = functools.partial(stub_cast_to_cells, **kwargs)

    stubs.Set(api, '_call_to_cells', call)
    stubs.Set(api, '_cast_to_cells', cast)


class CellsComputeAPITestCase(test_compute.ComputeAPITestCase):
    def setUp(self):
        super(CellsComputeAPITestCase, self).setUp()
        global ORIG_COMPUTE_API
        ORIG_COMPUTE_API = self.compute_api
        self.flags(enable=True, group='cells')

        def _fake_cell_read_only(*args, **kwargs):
            return False

        def _fake_validate_cell(*args, **kwargs):
            return

        def _nop_update(context, instance, **kwargs):
            return instance

        self.compute_api = compute_cells_api.ComputeCellsAPI()
        self.stubs.Set(self.compute_api, '_cell_read_only',
                _fake_cell_read_only)
        self.stubs.Set(self.compute_api, '_validate_cell',
                _fake_validate_cell)

        # NOTE(belliott) Don't update the instance state
        # for the tests at the API layer.  Let it happen after
        # the stub cast to cells so that expected_task_states
        # match.
        self.stubs.Set(self.compute_api, 'update', _nop_update)

        deploy_stubs(self.stubs, self.compute_api)

    def tearDown(self):
        global ORIG_COMPUTE_API
        self.compute_api = ORIG_COMPUTE_API
        super(CellsComputeAPITestCase, self).tearDown()

    def test_instance_metadata(self):
        self.skipTest("Test is incompatible with cells.")

    def test_evacuate(self):
        self.skipTest("Test is incompatible with cells.")

    def test_error_evacuate(self):
        self.skipTest("Test is incompatible with cells.")

    def test_delete_instance_no_cell(self):
        cells_rpcapi = self.compute_api.cells_rpcapi
        self.mox.StubOutWithMock(cells_rpcapi,
                                 'instance_delete_everywhere')
        inst = self._create_fake_instance_obj()
        cells_rpcapi.instance_delete_everywhere(self.context,
                inst, delete_types.DELETE)
        self.mox.ReplayAll()
        self.stubs.Set(self.compute_api.network_api, 'deallocate_for_instance',
                       lambda *a, **kw: None)
        self.compute_api.delete(self.context, inst)

    def test_soft_delete_instance_no_cell(self):
        cells_rpcapi = self.compute_api.cells_rpcapi
        self.mox.StubOutWithMock(cells_rpcapi,
                                 'instance_delete_everywhere')
        inst = self._create_fake_instance_obj()
        cells_rpcapi.instance_delete_everywhere(self.context,
                inst, delete_types.SOFT_DELETE)
        self.mox.ReplayAll()
        self.stubs.Set(self.compute_api.network_api, 'deallocate_for_instance',
                       lambda *a, **kw: None)
        self.compute_api.soft_delete(self.context, inst)

    def test_get_migrations(self):
        filters = {'cell_name': 'ChildCell', 'status': 'confirmed'}
        migrations = {'migrations': [{'id': 1234}]}
        cells_rpcapi = self.compute_api.cells_rpcapi
        self.mox.StubOutWithMock(cells_rpcapi, 'get_migrations')
        cells_rpcapi.get_migrations(self.context,
                                        filters).AndReturn(migrations)
        self.mox.ReplayAll()

        response = self.compute_api.get_migrations(self.context, filters)

        self.assertEqual(migrations, response)

    @mock.patch('nova.cells.messaging._TargetedMessage')
    def test_rebuild_sig(self, mock_msg):
        # TODO(belliott) Cells could benefit from better testing to ensure API
        # and manager signatures stay up to date

        def wire(version):
            # wire the rpc cast directly to the manager method to make sure
            # the signature matches
            cells_mgr = manager.CellsManager()

            def cast(context, method, *args, **kwargs):
                fn = getattr(cells_mgr, method)
                fn(context, *args, **kwargs)

            cells_mgr.cast = cast
            return cells_mgr

        cells_rpcapi = self.compute_api.cells_rpcapi
        client = cells_rpcapi.client

        with mock.patch.object(client, 'prepare', side_effect=wire):
            inst = self._create_fake_instance_obj()
            inst.cell_name = 'mycell'

            cells_rpcapi.rebuild_instance(self.context, inst, 'pass', None,
                                          None, None, None, None,
                                          recreate=False,
                                          on_shared_storage=False, host='host',
                                          preserve_ephemeral=True, kwargs=None)

        # one targeted message should have been created
        self.assertEqual(1, mock_msg.call_count)


class CellsConductorAPIRPCRedirect(test.NoDBTestCase):
    def setUp(self):
        super(CellsConductorAPIRPCRedirect, self).setUp()

        self.compute_api = compute_cells_api.ComputeCellsAPI()
        self.cells_rpcapi = mock.MagicMock()
        self.compute_api._compute_task_api.cells_rpcapi = self.cells_rpcapi

        self.context = context.RequestContext('fake', 'fake')

    @mock.patch.object(compute_api.API, '_record_action_start')
    @mock.patch.object(compute_api.API, '_provision_instances')
    @mock.patch.object(compute_api.API, '_check_and_transform_bdm')
    @mock.patch.object(compute_api.API, '_get_image')
    @mock.patch.object(compute_api.API, '_validate_and_build_base_options')
    def test_build_instances(self, _validate, _get_image, _check_bdm,
                             _provision, _record_action_start):
        _get_image.return_value = (None, 'fake-image')
        _validate.return_value = ({}, 1)
        _check_bdm.return_value = 'bdms'
        _provision.return_value = 'instances'

        self.compute_api.create(self.context, 'fake-flavor', 'fake-image')

        # Subsequent tests in class are verifying the hooking.  We don't check
        # args since this is verified in compute test code.
        self.assertTrue(self.cells_rpcapi.build_instances.called)

    @mock.patch.object(compute_api.API, '_record_action_start')
    @mock.patch.object(compute_api.API, '_resize_cells_support')
    @mock.patch.object(compute_api.API, '_reserve_quota_delta')
    @mock.patch.object(compute_api.API, '_upsize_quota_delta')
    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(flavors, 'extract_flavor')
    @mock.patch.object(compute_api.API, '_check_auto_disk_config')
    def test_resize_instance(self, _check, _extract, _save, _upsize, _reserve,
                             _cells, _record):
        _extract.return_value = objects.Flavor(**test_flavor.fake_flavor)
        orig_system_metadata = {}
        instance = fake_instance.fake_instance_obj(self.context,
                vm_state=vm_states.ACTIVE, cell_name='fake-cell',
                launched_at=timeutils.utcnow(),
                system_metadata=orig_system_metadata,
                expected_attrs=['system_metadata'])

        self.compute_api.resize(self.context, instance)
        self.assertTrue(self.cells_rpcapi.resize_instance.called)

    @mock.patch.object(compute_api.API, '_record_action_start')
    @mock.patch.object(objects.Instance, 'save')
    def test_live_migrate_instance(self, instance_save, _record):
        orig_system_metadata = {}
        instance = fake_instance.fake_instance_obj(self.context,
                vm_state=vm_states.ACTIVE, cell_name='fake-cell',
                launched_at=timeutils.utcnow(),
                system_metadata=orig_system_metadata,
                expected_attrs=['system_metadata'])

        self.compute_api.live_migrate(self.context, instance,
                True, True, 'fake_dest_host')

        self.assertTrue(self.cells_rpcapi.live_migrate_instance.called)

    @mock.patch.object(objects.Instance, 'save')
    @mock.patch.object(objects.Instance, 'get_flavor')
    @mock.patch.object(objects.BlockDeviceMappingList, 'get_by_instance_uuid')
    @mock.patch.object(compute_api.API, '_get_image')
    @mock.patch.object(compute_api.API, '_check_auto_disk_config')
    @mock.patch.object(compute_api.API, '_checks_for_create_and_rebuild')
    @mock.patch.object(compute_api.API, '_record_action_start')
    def test_rebuild_instance(self, _record_action_start,
        _checks_for_create_and_rebuild, _check_auto_disk_config,
        _get_image, bdm_get_by_instance_uuid, get_flavor, instance_save):
        orig_system_metadata = {}
        instance = fake_instance.fake_instance_obj(self.context,
                vm_state=vm_states.ACTIVE, cell_name='fake-cell',
                launched_at=timeutils.utcnow(),
                system_metadata=orig_system_metadata,
                expected_attrs=['system_metadata'])
        get_flavor.return_value = ''
        image_href = ''
        image = {"min_ram": 10, "min_disk": 1,
                 "properties": {'architecture': 'x86_64'}}
        admin_pass = ''
        files_to_inject = []
        bdms = []

        _get_image.return_value = (None, image)
        bdm_get_by_instance_uuid.return_value = bdms

        self.compute_api.rebuild(self.context, instance, image_href,
                                 admin_pass, files_to_inject)

        self.assertTrue(self.cells_rpcapi.rebuild_instance.called)

    def test_check_equal(self):
        task_api = self.compute_api.compute_task_api
        tests = set()
        for (name, value) in inspect.getmembers(self, inspect.ismethod):
            if name.startswith('test_') and name != 'test_check_equal':
                tests.add(name[5:])
        if tests != set(task_api.cells_compatible):
            self.fail("Testcases not equivalent to cells_compatible list")


class CellsComputePolicyTestCase(test_compute.ComputePolicyTestCase):
    def setUp(self):
        super(CellsComputePolicyTestCase, self).setUp()
        global ORIG_COMPUTE_API
        ORIG_COMPUTE_API = self.compute_api
        self.compute_api = compute_cells_api.ComputeCellsAPI()
        deploy_stubs(self.stubs, self.compute_api)

    def tearDown(self):
        global ORIG_COMPUTE_API
        self.compute_api = ORIG_COMPUTE_API
        super(CellsComputePolicyTestCase, self).tearDown()
