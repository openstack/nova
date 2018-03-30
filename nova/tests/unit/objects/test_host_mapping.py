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

from nova import context
from nova import exception
from nova import objects
from nova.objects import host_mapping
from nova import test
from nova.tests.unit.objects import test_cell_mapping
from nova.tests.unit.objects import test_objects
from nova.tests import uuidsentinel as uuids


def get_db_mapping(mapped_cell=None, **updates):
    db_mapping = {
            'id': 1,
            'cell_id': None,
            'host': 'fake-host',
            'created_at': None,
            'updated_at': None,
            }
    if mapped_cell:
        db_mapping["cell_mapping"] = mapped_cell
    else:
        db_mapping["cell_mapping"] = test_cell_mapping.get_db_mapping(id=42)
    db_mapping['cell_id'] = db_mapping["cell_mapping"]["id"]
    db_mapping.update(updates)
    return db_mapping


class _TestHostMappingObject(object):
    def _check_cell_map_value(self, db_val, cell_obj):
        self.assertEqual(db_val, cell_obj.id)

    @mock.patch.object(host_mapping.HostMapping,
            '_get_by_host_from_db')
    def test_get_by_host(self, host_from_db):
        fake_cell = test_cell_mapping.get_db_mapping(id=1)
        db_mapping = get_db_mapping(mapped_cell=fake_cell)
        host_from_db.return_value = db_mapping

        mapping_obj = objects.HostMapping().get_by_host(
                self.context, db_mapping['host'])
        host_from_db.assert_called_once_with(self.context,
                db_mapping['host'])
        with mock.patch.object(
                host_mapping.HostMapping, '_get_cell_mapping') as mock_load:
            self.compare_obj(mapping_obj, db_mapping,
                             subs={'cell_mapping': 'cell_id'},
                             comparators={
                                 'cell_mapping': self._check_cell_map_value})
            # Check that lazy loading isn't happening
            self.assertFalse(mock_load.called)

    def test_from_db_object_no_cell_map(self):
        """Test when db object does not have cell_mapping"""
        fake_cell = test_cell_mapping.get_db_mapping(id=1)
        db_mapping = get_db_mapping(mapped_cell=fake_cell)
        # If db object has no cell_mapping, lazy loading should occur
        db_mapping.pop("cell_mapping")
        fake_cell_obj = objects.CellMapping(self.context, **fake_cell)

        mapping_obj = objects.HostMapping()._from_db_object(
                self.context, objects.HostMapping(), db_mapping)
        with mock.patch.object(
                host_mapping.HostMapping, '_get_cell_mapping') as mock_load:
            mock_load.return_value = fake_cell_obj
            self.compare_obj(mapping_obj, db_mapping,
                             subs={'cell_mapping': 'cell_id'},
                             comparators={
                                 'cell_mapping': self._check_cell_map_value})
            # Check that cell_mapping is lazy loaded
            mock_load.assert_called_once_with()

    @mock.patch.object(host_mapping.HostMapping, '_create_in_db')
    def test_create(self, create_in_db):
        fake_cell = test_cell_mapping.get_db_mapping(id=1)
        db_mapping = get_db_mapping(mapped_cell=fake_cell)
        db_mapping.pop("cell_mapping")
        host = db_mapping['host']
        create_in_db.return_value = db_mapping

        fake_cell_obj = objects.CellMapping(self.context, **fake_cell)
        mapping_obj = objects.HostMapping(self.context)
        mapping_obj.host = host
        mapping_obj.cell_mapping = fake_cell_obj
        mapping_obj.create()

        create_in_db.assert_called_once_with(self.context,
                {'host': host,
                 'cell_id': fake_cell["id"]})
        self.compare_obj(mapping_obj, db_mapping,
                         subs={'cell_mapping': 'cell_id'},
                         comparators={
                             'cell_mapping': self._check_cell_map_value})

    @mock.patch.object(host_mapping.HostMapping, '_save_in_db')
    def test_save(self, save_in_db):
        db_mapping = get_db_mapping()
        # This isn't needed here
        db_mapping.pop("cell_mapping")
        host = db_mapping['host']
        mapping_obj = objects.HostMapping(self.context)
        mapping_obj.host = host
        mapping_obj.id = db_mapping['id']
        new_fake_cell = test_cell_mapping.get_db_mapping(id=10)
        fake_cell_obj = objects.CellMapping(self.context, **new_fake_cell)
        mapping_obj.cell_mapping = fake_cell_obj
        db_mapping.update({"cell_id": new_fake_cell["id"]})
        save_in_db.return_value = db_mapping

        mapping_obj.save()
        save_in_db.assert_called_once_with(self.context,
                test.MatchType(host_mapping.HostMapping),
                {'cell_id': new_fake_cell["id"],
                 'host': host,
                 'id': db_mapping['id']})
        self.compare_obj(mapping_obj, db_mapping,
                         subs={'cell_mapping': 'cell_id'},
                         comparators={
                             'cell_mapping': self._check_cell_map_value})

    @mock.patch.object(host_mapping.HostMapping, '_destroy_in_db')
    def test_destroy(self, destroy_in_db):
        mapping_obj = objects.HostMapping(self.context)
        mapping_obj.host = "fake-host2"

        mapping_obj.destroy()
        destroy_in_db.assert_called_once_with(self.context, "fake-host2")


class TestHostMappingObject(test_objects._LocalTest,
                            _TestHostMappingObject):
    pass


class TestRemoteHostMappingObject(test_objects._RemoteTest,
                                  _TestHostMappingObject):
    pass


class TestHostMappingDiscovery(test.NoDBTestCase):
    @mock.patch('nova.objects.CellMappingList.get_all')
    @mock.patch('nova.objects.HostMapping.create')
    @mock.patch('nova.objects.HostMapping.get_by_host')
    @mock.patch('nova.objects.ComputeNodeList.get_all_by_not_mapped')
    def test_discover_hosts_all(self, mock_cn_get, mock_hm_get, mock_hm_create,
                                mock_cm):
        def _hm_get(context, host):
            if host in ['a', 'b', 'c']:
                return objects.HostMapping()
            raise exception.HostMappingNotFound(name=host)

        mock_hm_get.side_effect = _hm_get
        mock_cn_get.side_effect = [[objects.ComputeNode(host='d',
                                                        uuid=uuids.cn1)],
                                   [objects.ComputeNode(host='e',
                                                        uuid=uuids.cn2)]]

        cell_mappings = [objects.CellMapping(name='foo',
                                             uuid=uuids.cm1),
                         objects.CellMapping(name='bar',
                                             uuid=uuids.cm2)]
        mock_cm.return_value = cell_mappings
        ctxt = context.get_admin_context()
        with mock.patch('nova.objects.ComputeNode.save') as mock_save:
            hms = host_mapping.discover_hosts(ctxt)
            mock_save.assert_has_calls([mock.call(), mock.call()])
        self.assertEqual(2, len(hms))
        self.assertTrue(mock_hm_create.called)
        self.assertEqual(['d', 'e'],
                         [hm.host for hm in hms])

    @mock.patch('nova.objects.CellMapping.get_by_uuid')
    @mock.patch('nova.objects.HostMapping.create')
    @mock.patch('nova.objects.HostMapping.get_by_host')
    @mock.patch('nova.objects.ComputeNodeList.get_all_by_not_mapped')
    def test_discover_hosts_one(self, mock_cn_get, mock_hm_get, mock_hm_create,
                                mock_cm):
        def _hm_get(context, host):
            if host in ['a', 'b', 'c']:
                return objects.HostMapping()
            raise exception.HostMappingNotFound(name=host)

        mock_hm_get.side_effect = _hm_get
        # NOTE(danms): Provide both side effects, but expect it to only
        # be called once if we provide a cell
        mock_cn_get.side_effect = [[objects.ComputeNode(host='d',
                                                        uuid=uuids.cn1)],
                                   [objects.ComputeNode(host='e',
                                                        uuid=uuids.cn2)]]

        mock_cm.return_value = objects.CellMapping(name='foo',
                                                   uuid=uuids.cm1)
        ctxt = context.get_admin_context()
        with mock.patch('nova.objects.ComputeNode.save') as mock_save:
            hms = host_mapping.discover_hosts(ctxt, uuids.cm1)
            mock_save.assert_called_once_with()
        self.assertEqual(1, len(hms))
        self.assertTrue(mock_hm_create.called)
        self.assertEqual(['d'],
                         [hm.host for hm in hms])

    @mock.patch('nova.objects.CellMappingList.get_all')
    @mock.patch('nova.objects.HostMapping.get_by_host')
    @mock.patch('nova.objects.HostMapping.create')
    @mock.patch('nova.objects.ServiceList.get_by_binary')
    def test_discover_services(self, mock_srv, mock_hm_create,
                               mock_hm_get, mock_cm):
        mock_cm.return_value = [
            objects.CellMapping(uuid=uuids.cell1),
            objects.CellMapping(uuid=uuids.cell2),
        ]
        mock_srv.side_effect = [
            [objects.Service(host='host1'),
             objects.Service(host='host2')],
            [objects.Service(host='host3')],
        ]

        def fake_get_host_mapping(ctxt, host):
            if host == 'host2':
                return
            else:
                raise exception.HostMappingNotFound(name=host)

        mock_hm_get.side_effect = fake_get_host_mapping

        ctxt = context.get_admin_context()
        mappings = host_mapping.discover_hosts(ctxt, by_service=True)
        self.assertEqual(2, len(mappings))
        self.assertEqual(['host1', 'host3'],
                         sorted([m.host for m in mappings]))

    @mock.patch('nova.objects.CellMapping.get_by_uuid')
    @mock.patch('nova.objects.HostMapping.get_by_host')
    @mock.patch('nova.objects.HostMapping.create')
    @mock.patch('nova.objects.ServiceList.get_by_binary')
    def test_discover_services_one_cell(self, mock_srv, mock_hm_create,
                                        mock_hm_get, mock_cm):
        mock_cm.return_value = objects.CellMapping(uuid=uuids.cell1)
        mock_srv.return_value = [
            objects.Service(host='host1'),
            objects.Service(host='host2'),
        ]

        def fake_get_host_mapping(ctxt, host):
            if host == 'host2':
                return
            else:
                raise exception.HostMappingNotFound(name=host)

        mock_hm_get.side_effect = fake_get_host_mapping

        lines = []

        def fake_status(msg):
            lines.append(msg)

        ctxt = context.get_admin_context()
        mappings = host_mapping.discover_hosts(ctxt, cell_uuid=uuids.cell1,
                                               status_fn=fake_status,
                                               by_service=True)
        self.assertEqual(1, len(mappings))
        self.assertEqual(['host1'],
                         sorted([m.host for m in mappings]))

        expected = """\
Getting computes from cell: %(cell)s
Creating host mapping for service host1
Found 1 unmapped computes in cell: %(cell)s""" % {'cell': uuids.cell1}

        self.assertEqual(expected, '\n'.join(lines))
