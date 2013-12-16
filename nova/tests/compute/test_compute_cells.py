# vim: tabstop=4 shiftwidth=4 softtabstop=4
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

from oslo.config import cfg

from nova.compute import api as compute_api
from nova.compute import cells_api as compute_cells_api
from nova import db
from nova.openstack.common import jsonutils
from nova import quota
from nova.tests.compute import test_compute


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


def wrap_create_instance(func):
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        instance = self._create_fake_instance()

        def fake(*args, **kwargs):
            return instance

        self.stubs.Set(self, '_create_fake_instance', fake)
        original_instance = jsonutils.to_primitive(instance)
        deploy_stubs(self.stubs, self.compute_api,
                     original_instance=original_instance)
        return func(self, *args, **kwargs)

    return wrapper


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

    def test_delete_instance_no_cell(self):
        cells_rpcapi = self.compute_api.cells_rpcapi
        self.mox.StubOutWithMock(cells_rpcapi,
                                 'instance_delete_everywhere')
        inst = self._create_fake_instance_obj()
        cells_rpcapi.instance_delete_everywhere(self.context,
                inst, 'hard')
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
                inst, 'soft')
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
