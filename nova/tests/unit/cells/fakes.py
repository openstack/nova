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
Fakes For Cells tests.
"""

from nova.cells import driver
from nova.cells import manager as cells_manager
from nova.cells import state as cells_state
from nova.cells import utils as cells_utils
import nova.conf
import nova.db
from nova.db import base
from nova import exception
from nova import objects

CONF = nova.conf.CONF


# Fake Cell Hierarchy
FAKE_TOP_LEVEL_CELL_NAME = 'api-cell'
FAKE_CELL_LAYOUT = [{'child-cell1': []},
                    {'child-cell2': [{'grandchild-cell1': []}]},
                    {'child-cell3': [{'grandchild-cell2': []},
                                     {'grandchild-cell3': []}]},
                    {'child-cell4': []}]

# build_cell_stub_infos() below will take the above layout and create
# a fake view of the DB from the perspective of each of the cells.
# For each cell, a CellStubInfo will be created with this info.
CELL_NAME_TO_STUB_INFO = {}


class FakeDBApi(object):
    """Cells uses a different DB in each cell.  This means in order to
    stub out things differently per cell, I need to create a fake DBApi
    object that is instantiated by each fake cell.
    """
    def __init__(self, cell_db_entries):
        self.cell_db_entries = cell_db_entries

    def __getattr__(self, key):
        return getattr(nova.db, key)

    def cell_get_all(self, ctxt):
        return self.cell_db_entries

    def instance_get_all_by_filters(self, ctxt, *args, **kwargs):
        return []

    def instance_get_by_uuid(self, ctxt, instance_uuid):
        raise exception.InstanceNotFound(instance_id=instance_uuid)


class FakeCellsDriver(driver.BaseCellsDriver):
    pass


class FakeCellState(cells_state.CellState):
    def send_message(self, message):
        message_runner = get_message_runner(self.name)
        orig_ctxt = message.ctxt
        json_message = message.to_json()
        message = message_runner.message_from_json(json_message)
        # Restore this so we can use mox and verify same context
        message.ctxt = orig_ctxt
        message.process()


class FakeCellStateManager(cells_state.CellStateManagerDB):
    def __init__(self, *args, **kwargs):
        super(FakeCellStateManager, self).__init__(*args,
                cell_state_cls=FakeCellState, **kwargs)


class FakeCellsManager(cells_manager.CellsManager):
    def __init__(self, *args, **kwargs):
        super(FakeCellsManager, self).__init__(*args,
                cell_state_manager=FakeCellStateManager,
                **kwargs)


class CellStubInfo(object):
    def __init__(self, test_case, cell_name, db_entries):
        self.test_case = test_case
        self.cell_name = cell_name
        self.db_entries = db_entries

        def fake_base_init(_self, *args, **kwargs):
            _self.db = FakeDBApi(db_entries)

        @staticmethod
        def _fake_compute_node_get_all(context):
            return []

        @staticmethod
        def _fake_service_get_by_binary(context, binary):
            return []

        test_case.stubs.Set(base.Base, '__init__', fake_base_init)
        test_case.stubs.Set(objects.ComputeNodeList, 'get_all',
                            _fake_compute_node_get_all)
        test_case.stubs.Set(objects.ServiceList, 'get_by_binary',
                            _fake_service_get_by_binary)
        self.cells_manager = FakeCellsManager()
        # Fix the cell name, as it normally uses CONF.cells.name
        msg_runner = self.cells_manager.msg_runner
        msg_runner.our_name = self.cell_name
        self.cells_manager.state_manager.my_cell_state.name = self.cell_name


def _build_cell_transport_url(cur_db_id):
    username = 'username%s' % cur_db_id
    password = 'password%s' % cur_db_id
    hostname = 'rpc_host%s' % cur_db_id
    port = 3090 + cur_db_id
    virtual_host = 'rpc_vhost%s' % cur_db_id

    return 'rabbit://%s:%s@%s:%s/%s' % (username, password, hostname, port,
                                        virtual_host)


def _build_cell_stub_info(test_case, our_name, parent_path, children):
    cell_db_entries = []
    cur_db_id = 1
    sep_char = cells_utils.PATH_CELL_SEP
    if parent_path:
        cell_db_entries.append(
                dict(id=cur_db_id,
                     name=parent_path.split(sep_char)[-1],
                     is_parent=True,
                     transport_url=_build_cell_transport_url(cur_db_id)))
        cur_db_id += 1
        our_path = parent_path + sep_char + our_name
    else:
        our_path = our_name
    for child in children:
        for child_name, grandchildren in child.items():
            _build_cell_stub_info(test_case, child_name, our_path,
                    grandchildren)
            cell_entry = dict(id=cur_db_id,
                              name=child_name,
                              transport_url=_build_cell_transport_url(
                                  cur_db_id),
                              is_parent=False)
            cell_db_entries.append(cell_entry)
            cur_db_id += 1
    stub_info = CellStubInfo(test_case, our_name, cell_db_entries)
    CELL_NAME_TO_STUB_INFO[our_name] = stub_info


def _build_cell_stub_infos(test_case):
    _build_cell_stub_info(test_case, FAKE_TOP_LEVEL_CELL_NAME, '',
            FAKE_CELL_LAYOUT)


def init(test_case):
    global CELL_NAME_TO_STUB_INFO
    test_case.flags(driver='nova.tests.unit.cells.fakes.FakeCellsDriver',
            group='cells')
    CELL_NAME_TO_STUB_INFO = {}
    _build_cell_stub_infos(test_case)


def _get_cell_stub_info(cell_name):
    return CELL_NAME_TO_STUB_INFO[cell_name]


def get_state_manager(cell_name):
    return _get_cell_stub_info(cell_name).cells_manager.state_manager


def get_cell_state(cur_cell_name, tgt_cell_name):
    state_manager = get_state_manager(cur_cell_name)
    cell = state_manager.child_cells.get(tgt_cell_name)
    if cell is None:
        cell = state_manager.parent_cells.get(tgt_cell_name)
    return cell


def get_cells_manager(cell_name):
    return _get_cell_stub_info(cell_name).cells_manager


def get_message_runner(cell_name):
    return _get_cell_stub_info(cell_name).cells_manager.msg_runner


def stub_tgt_method(test_case, cell_name, method_name, method):
    msg_runner = get_message_runner(cell_name)
    tgt_msg_methods = msg_runner.methods_by_type['targeted']
    setattr(tgt_msg_methods, method_name, method)


def stub_bcast_method(test_case, cell_name, method_name, method):
    msg_runner = get_message_runner(cell_name)
    tgt_msg_methods = msg_runner.methods_by_type['broadcast']
    setattr(tgt_msg_methods, method_name, method)


def stub_bcast_methods(test_case, method_name, method):
    for cell_name in CELL_NAME_TO_STUB_INFO.keys():
        stub_bcast_method(test_case, cell_name, method_name, method)
