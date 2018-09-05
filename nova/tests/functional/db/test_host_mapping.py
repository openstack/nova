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
from oslo_utils.fixture import uuidsentinel as uuids
from oslo_utils import uuidutils

from nova import context
from nova import exception
from nova import objects
from nova.objects import cell_mapping
from nova.objects import host_mapping
from nova import test
from nova.tests import fixtures


sample_mapping = {'host': 'fake-host',
                  'cell_mapping': None}


sample_cell_mapping = {'id': 1,
                       'uuid': '',
                       'name': 'fake-cell',
                       'transport_url': 'rabbit:///',
                       'database_connection': 'mysql:///'}


def create_cell_mapping(**kwargs):
    args = sample_cell_mapping.copy()
    if 'uuid' not in kwargs:
        args['uuid'] = uuidutils.generate_uuid()
    args.update(kwargs)
    ctxt = context.RequestContext('fake-user', 'fake-project')
    return cell_mapping.CellMapping._create_in_db(ctxt, args)


def create_mapping(**kwargs):
    args = sample_mapping.copy()
    args.update(kwargs)
    if args["cell_mapping"] is None:
        args["cell_mapping"] = create_cell_mapping()
    args["cell_id"] = args.pop("cell_mapping", {}).get("id")
    ctxt = context.RequestContext('fake-user', 'fake-project')
    return host_mapping.HostMapping._create_in_db(ctxt, args)


def create_mapping_obj(context, **kwargs):
    mapping = create_mapping(**kwargs)
    return host_mapping.HostMapping._from_db_object(
        context, host_mapping.HostMapping(), mapping)


class HostMappingTestCase(test.NoDBTestCase):
    USES_DB_SELF = True

    def setUp(self):
        super(HostMappingTestCase, self).setUp()
        self.useFixture(fixtures.Database(database='api'))
        self.context = context.RequestContext('fake-user', 'fake-project')
        self.mapping_obj = host_mapping.HostMapping()
        self.cell_mapping_obj = cell_mapping.CellMapping()

    def _compare_cell_obj_to_mapping(self, obj, mapping):
        for key in [key for key in self.cell_mapping_obj.fields.keys()
                    if key not in ("created_at", "updated_at")]:
            self.assertEqual(getattr(obj, key), mapping[key])

    def test_get_by_host(self):
        mapping = create_mapping()
        db_mapping = self.mapping_obj._get_by_host_from_db(
                self.context, mapping['host'])
        for key in self.mapping_obj.fields.keys():
            if key == "cell_mapping":
                key = "cell_id"
            self.assertEqual(db_mapping[key], mapping[key])

    def test_get_by_host_not_found(self):
        self.assertRaises(exception.HostMappingNotFound,
                self.mapping_obj._get_by_host_from_db, self.context,
                'fake-host2')

    def test_update_cell_mapping(self):
        db_hm = create_mapping()
        db_cell = create_cell_mapping(id=42)
        cell = cell_mapping.CellMapping.get_by_uuid(
            self.context, db_cell['uuid'])
        hm = host_mapping.HostMapping(self.context)
        hm.id = db_hm['id']
        hm.cell_mapping = cell
        hm.save()
        self.assertNotEqual(db_hm['cell_id'], hm.cell_mapping.id)
        for key in hm.fields.keys():
            if key in ('updated_at', 'cell_mapping'):
                continue
            model_field = getattr(hm, key)
            if key == 'created_at':
                model_field = model_field.replace(tzinfo=None)
            self.assertEqual(db_hm[key], model_field, 'field %s' % key)
        db_hm_new = host_mapping.HostMapping._get_by_host_from_db(
            self.context, db_hm['host'])
        self.assertNotEqual(db_hm['cell_id'], db_hm_new['cell_id'])

    def test_destroy_in_db(self):
        mapping = create_mapping()
        self.mapping_obj._get_by_host_from_db(self.context,
                mapping['host'])
        self.mapping_obj._destroy_in_db(self.context, mapping['host'])
        self.assertRaises(exception.HostMappingNotFound,
                self.mapping_obj._get_by_host_from_db, self.context,
                mapping['host'])

    def test_load_cell_mapping(self):
        cell = create_cell_mapping(id=42)
        mapping_obj = create_mapping_obj(self.context, cell_mapping=cell)
        cell_map_obj = mapping_obj.cell_mapping
        self._compare_cell_obj_to_mapping(cell_map_obj, cell)

    def test_host_mapping_list_get_by_cell_id(self):
        """Tests getting all of the HostMappings for a given CellMapping id.
        """
        # we shouldn't have any host mappings yet
        self.assertEqual(0, len(host_mapping.HostMappingList.get_by_cell_id(
            self.context, sample_cell_mapping['id'])))
        # now create a host mapping
        db_host_mapping = create_mapping()
        # now we should list out one host mapping for the cell
        host_mapping_list = host_mapping.HostMappingList.get_by_cell_id(
            self.context, db_host_mapping['cell_id'])
        self.assertEqual(1, len(host_mapping_list))
        self.assertEqual(db_host_mapping['id'], host_mapping_list[0].id)


class HostMappingDiscoveryTest(test.TestCase):
    def _setup_cells(self):
        ctxt = context.get_admin_context()
        self.celldbs = fixtures.CellDatabases()
        cells = []
        for uuid in (uuids.cell1, uuids.cell2, uuids.cell3):
            cm = objects.CellMapping(context=ctxt,
                                     uuid=uuid,
                                     database_connection=uuid,
                                     transport_url='fake://')
            cm.create()
            cells.append(cm)
            self.celldbs.add_cell_database(uuid)
        self.useFixture(self.celldbs)

        for cell in cells:
            for i in (1, 2, 3):
                # Make one host in each cell unmapped
                mapped = 0 if i == 2 else 1

                host = 'host-%s-%i' % (cell.uuid, i)
                if mapped:
                    hm = objects.HostMapping(context=ctxt,
                                             cell_mapping=cell,
                                             host=host)
                    hm.create()

                with context.target_cell(ctxt, cell):
                    cn = objects.ComputeNode(
                        context=ctxt, vcpus=1, memory_mb=1, local_gb=1,
                        vcpus_used=0, memory_mb_used=0, local_gb_used=0,
                        hypervisor_type='danvm', hypervisor_version='1',
                        cpu_info='foo',
                        cpu_allocation_ratio=1.0,
                        ram_allocation_ratio=1.0,
                        disk_allocation_ratio=1.0,
                        mapped=mapped, host=host)
                    cn.create()

    def test_discover_hosts(self):
        status = lambda m: None

        ctxt = context.get_admin_context()

        # NOTE(danms): Three cells, one unmapped host per cell
        mappings = host_mapping.discover_hosts(ctxt, status_fn=status)
        self.assertEqual(3, len(mappings))

        # NOTE(danms): All hosts should be mapped now, so we should do
        # no lookups for them
        with mock.patch('nova.objects.HostMapping.get_by_host') as mock_gbh:
            mappings = host_mapping.discover_hosts(ctxt, status_fn=status)
            self.assertFalse(mock_gbh.called)
        self.assertEqual(0, len(mappings))

    def test_discover_hosts_one_cell(self):
        status = lambda m: None

        ctxt = context.get_admin_context()
        cells = objects.CellMappingList.get_all(ctxt)

        # NOTE(danms): One cell, one unmapped host per cell
        mappings = host_mapping.discover_hosts(ctxt, cells[1].uuid,
                                               status_fn=status)
        self.assertEqual(1, len(mappings))

        # NOTE(danms): Three cells, two with one more unmapped host
        mappings = host_mapping.discover_hosts(ctxt, status_fn=status)
        self.assertEqual(2, len(mappings))

        # NOTE(danms): All hosts should be mapped now, so we should do
        # no lookups for them
        with mock.patch('nova.objects.HostMapping.get_by_host') as mock_gbh:
            mappings = host_mapping.discover_hosts(ctxt, status_fn=status)
            self.assertFalse(mock_gbh.called)
        self.assertEqual(0, len(mappings))
