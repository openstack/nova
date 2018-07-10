# Copyright 2012 Nebula, Inc.
# Copyright 2013 IBM Corp.
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

import mock
from six.moves import range

from nova.cells import state
from nova.db.sqlalchemy import models
from nova import exception
from nova.tests.functional.api_sample_tests import api_sample_base


class CellsSampleJsonTest(api_sample_base.ApiSampleTestBaseV21):
    sample_dir = "os-cells"

    def setUp(self):
        # db_check_interval < 0 makes cells manager always hit the DB
        self.flags(enable=True, db_check_interval=-1, group='cells')
        super(CellsSampleJsonTest, self).setUp()
        self.cells = self.start_service('cells',
                                 manager='nova.cells.manager.CellsManager')
        self._stub_cells()

    def _stub_cells(self, num_cells=5):
        self.cell_list = []
        self.cells_next_id = 1

        def _fake_cell_get_all(context):
            return self.cell_list

        def _fake_cell_get(inst, context, cell_name):
            for cell in self.cell_list:
                if cell['name'] == cell_name:
                    return cell
            raise exception.CellNotFound(cell_name=cell_name)

        for x in range(num_cells):
            cell = models.Cell()
            our_id = self.cells_next_id
            self.cells_next_id += 1
            cell.update({'id': our_id,
                         'name': 'cell%s' % our_id,
                         'transport_url': 'rabbit://username%s@/' % our_id,
                         'is_parent': our_id % 2 == 0})
            self.cell_list.append(cell)

        self.stub_out('nova.db.api.cell_get_all', _fake_cell_get_all)
        self.stub_out('nova.cells.rpcapi.CellsAPI.cell_get', _fake_cell_get)

    def test_cells_empty_list(self):
        # Override this
        self._stub_cells(num_cells=0)
        response = self._do_get('os-cells')
        self._verify_response('cells-list-empty-resp', {}, response, 200)

    def test_cells_list(self):
        response = self._do_get('os-cells')
        self._verify_response('cells-list-resp', {}, response, 200)

    def test_cells_get(self):
        response = self._do_get('os-cells/cell3')
        self._verify_response('cells-get-resp', {}, response, 200)

    def test_get_cell_capacity(self):
        self._mock_cell_capacity()
        state_manager = state.CellStateManager()
        my_state = state_manager.get_my_state()
        response = self._do_get('os-cells/%s/capacities' %
                my_state.name)
        return self._verify_response('cells-capacities-resp',
                                        {}, response, 200)

    def test_get_all_cells_capacity(self):
        self._mock_cell_capacity()
        response = self._do_get('os-cells/capacities')
        return self._verify_response('cells-capacities-resp',
                                        {}, response, 200)

    def _mock_cell_capacity(self):
        response = {"ram_free":
                        {"units_by_mb": {"8192": 0, "512": 13,
                                         "4096": 1, "2048": 3, "16384": 0},
                         "total_mb": 7680},
                    "disk_free":
                        {"units_by_mb": {"81920": 11, "20480": 46,
                                         "40960": 23, "163840": 5, "0": 0},
                         "total_mb": 1052672}
        }
        goc_mock = mock.Mock()
        goc_mock.return_value = response
        self.cells.manager.state_manager.get_our_capacities = goc_mock
