# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 Openstack Foundation
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
Tests For Compute admin api w/ Cells
"""

from nova.api.openstack.compute.contrib import admin_actions
from nova.compute import cells_api as compute_cells_api
from nova.compute import vm_states
from nova.openstack.common import uuidutils
from nova import test
from nova.tests.api.openstack import fakes


INSTANCE_IDS = {'inst_id': 1}


class CellsAdminAPITestCase(test.TestCase):

    def setUp(self):
        super(CellsAdminAPITestCase, self).setUp()

        def _fake_cell_read_only(*args, **kwargs):
            return False

        def _fake_validate_cell(*args, **kwargs):
            return

        def _fake_compute_api_get(context, instance_id):
            return {'id': 1, 'uuid': instance_id, 'vm_state': vm_states.ACTIVE,
                    'task_state': None, 'cell_name': None}

        def _fake_instance_update_and_get_original(context, instance_uuid,
                                                   values):
            inst = fakes.stub_instance(INSTANCE_IDS.get(instance_uuid),
                                       name=values.get('display_name'))
            return (inst, inst)

        def fake_cast_to_cells(context, instance, method, *args, **kwargs):
            """
            Makes sure that the cells receive the cast to update
            the cell state
            """
            self.cells_received_kwargs.update(kwargs)

        self.admin_api = admin_actions.AdminActionsController()
        self.admin_api.compute_api = compute_cells_api.ComputeCellsAPI()
        self.stubs.Set(self.admin_api.compute_api, '_cell_read_only',
                       _fake_cell_read_only)
        self.stubs.Set(self.admin_api.compute_api, '_validate_cell',
                       _fake_validate_cell)
        self.stubs.Set(self.admin_api.compute_api, 'get',
                       _fake_compute_api_get)
        self.stubs.Set(self.admin_api.compute_api.db,
                       'instance_update_and_get_original',
                       _fake_instance_update_and_get_original)
        self.stubs.Set(self.admin_api.compute_api, '_cast_to_cells',
                       fake_cast_to_cells)

        self.uuid = uuidutils.generate_uuid()
        url = '/fake/servers/%s/action' % self.uuid
        self.request = fakes.HTTPRequest.blank(url)
        self.cells_received_kwargs = {}

    def test_reset_active(self):
        body = {"os-resetState": {"state": "error"}}
        result = self.admin_api._reset_state(self.request, 'inst_id', body)

        self.assertEqual(result.status_int, 202)
        # Make sure the cells received the update
        self.assertEqual(self.cells_received_kwargs,
                         dict(vm_state=vm_states.ERROR,
                              task_state=None))
