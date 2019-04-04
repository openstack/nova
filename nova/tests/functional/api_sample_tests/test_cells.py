# Copyright 2012 Nebula, Inc.
# Copyright 2013 IBM Corp.
# Copyright 2019 Red Hat, Inc.
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

from nova.tests.functional.api_sample_tests import api_sample_base


class CellsTest(api_sample_base.ApiSampleTestBaseV21):

    def test_cells_list(self):
        self.api.api_get('os-cells',
                         check_response_status=[410])

    def test_cells_capacity(self):
        self.api.api_get('os-cells/capacities',
                         check_response_status=[410])

    def test_cells_detail(self):
        self.api.api_get('os-cells/detail',
                         check_response_status=[410])

    def test_cells_info(self):
        self.api.api_get('os-cells/info',
                         check_response_status=[410])

    def test_cells_sync_instances(self):
        self.api.api_post('os-cells/sync_instances', {},
                          check_response_status=[410])

    def test_cell_create(self):
        self.api.api_post('os-cells', {},
                          check_response_status=[410])

    def test_cell_show(self):
        self.api.api_get('os-cells/cell3',
                         check_response_status=[410])

    def test_cell_update(self):
        self.api.api_put('os-cells/cell3', {},
                         check_response_status=[410])

    def test_cell_delete(self):
        self.api.api_delete('os-cells/cell3',
                            check_response_status=[410])

    def test_cell_capacity(self):
        self.api.api_get('os-cells/cell3/capacities',
                         check_response_status=[410])
