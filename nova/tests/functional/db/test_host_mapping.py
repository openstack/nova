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

from oslo_utils import uuidutils

from nova import context
from nova import exception
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

    def test_save_in_db(self):
        mapping = create_mapping()
        new_cell = create_cell_mapping(id=42)
        self.mapping_obj._save_in_db(self.context, mapping,
                {'cell_id': new_cell["id"]})
        db_mapping = self.mapping_obj._get_by_host_from_db(
                self.context, mapping['host'])
        self.assertNotEqual(db_mapping['cell_id'], mapping['cell_id'])
        for key in [key for key in self.mapping_obj.fields.keys()
                    if key not in ('updated_at', 'cell_id')]:
            if key == "cell_mapping":
                continue
            self.assertEqual(db_mapping[key], mapping[key])

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
