#    Copyright 2013 IBM Corp.
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

from nova.cells import opts as cells_opts
from nova.cells import rpcapi as cells_rpcapi
from nova import db
from nova import exception
from nova.network import model as network_model
from nova.objects import instance_info_cache
from nova.tests.unit.objects import test_objects


fake_info_cache = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': False,
    'instance_uuid': 'fake-uuid',
    'network_info': '[]',
    }


class _TestInstanceInfoCacheObject(object):
    def test_get_by_instance_uuid(self):
        nwinfo = network_model.NetworkInfo.hydrate([{'address': 'foo'}])
        self.mox.StubOutWithMock(db, 'instance_info_cache_get')
        db.instance_info_cache_get(self.context, 'fake-uuid').AndReturn(
            dict(fake_info_cache, network_info=nwinfo.json()))
        self.mox.ReplayAll()
        obj = instance_info_cache.InstanceInfoCache.get_by_instance_uuid(
            self.context, 'fake-uuid')
        self.assertEqual(obj.instance_uuid, 'fake-uuid')
        self.assertEqual(obj.network_info, nwinfo)
        self.assertRemotes()

    def test_get_by_instance_uuid_no_entries(self):
        self.mox.StubOutWithMock(db, 'instance_info_cache_get')
        db.instance_info_cache_get(self.context, 'fake-uuid').AndReturn(None)
        self.mox.ReplayAll()
        self.assertRaises(
                exception.InstanceInfoCacheNotFound,
                instance_info_cache.InstanceInfoCache.get_by_instance_uuid,
                self.context, 'fake-uuid')

    def test_new(self):
        obj = instance_info_cache.InstanceInfoCache.new(self.context,
                                                        'fake-uuid')
        self.assertEqual(set(['instance_uuid', 'network_info']),
                         obj.obj_what_changed())
        self.assertEqual('fake-uuid', obj.instance_uuid)
        self.assertIsNone(obj.network_info)

    def _save_helper(self, cell_type, update_cells):
        obj = instance_info_cache.InstanceInfoCache()
        cells_api = cells_rpcapi.CellsAPI()

        self.mox.StubOutWithMock(db, 'instance_info_cache_update')
        self.mox.StubOutWithMock(cells_opts, 'get_cell_type')
        self.mox.StubOutWithMock(cells_rpcapi, 'CellsAPI',
                                 use_mock_anything=True)
        self.mox.StubOutWithMock(cells_api,
                                 'instance_info_cache_update_at_top')
        nwinfo = network_model.NetworkInfo.hydrate([{'address': 'foo'}])
        db.instance_info_cache_update(
                self.context, 'fake-uuid',
                {'network_info': nwinfo.json()}).AndReturn('foo')
        if update_cells:
            cells_opts.get_cell_type().AndReturn(cell_type)
            if cell_type == 'compute':
                cells_rpcapi.CellsAPI().AndReturn(cells_api)
                cells_api.instance_info_cache_update_at_top(
                    self.context, 'foo')
        self.mox.ReplayAll()
        obj._context = self.context
        obj.instance_uuid = 'fake-uuid'
        obj.network_info = nwinfo
        obj.save(update_cells=update_cells)

    def test_save_with_update_cells_and_compute_cell(self):
        self._save_helper('compute', True)

    def test_save_with_update_cells_and_non_compute_cell(self):
        self._save_helper(None, True)

    def test_save_without_update_cells(self):
        self._save_helper(None, False)

    def test_refresh(self):
        obj = instance_info_cache.InstanceInfoCache.new(self.context,
                                                        'fake-uuid1')
        self.mox.StubOutWithMock(db, 'instance_info_cache_get')
        db.instance_info_cache_get(self.context, 'fake-uuid1').AndReturn(
            fake_info_cache)
        self.mox.ReplayAll()
        obj.refresh()
        self.assertEqual(fake_info_cache['instance_uuid'], obj.instance_uuid)


class TestInstanceInfoCacheObject(test_objects._LocalTest,
                                  _TestInstanceInfoCacheObject):
    pass


class TestInstanceInfoCacheObjectRemote(test_objects._RemoteTest,
                                        _TestInstanceInfoCacheObject):
    pass
