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

import datetime

import mock
from oslo_utils import timeutils

from nova.cells import opts as cells_opts
from nova.cells import rpcapi as cells_rpcapi
from nova import db
from nova import exception
from nova.network import model as network_model
from nova.objects import instance_info_cache
from nova.tests.unit.objects import test_objects
from nova.tests import uuidsentinel as uuids


fake_info_cache = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': False,
    'instance_uuid': uuids.info_instance,
    'network_info': '[]',
    }


class _TestInstanceInfoCacheObject(object):
    @mock.patch.object(db, 'instance_info_cache_get')
    def test_get_by_instance_uuid(self, mock_get):
        nwinfo = network_model.NetworkInfo.hydrate([{'address': 'foo'}])
        mock_get.return_value = dict(fake_info_cache,
                                     network_info=nwinfo.json())
        obj = instance_info_cache.InstanceInfoCache.get_by_instance_uuid(
            self.context, uuids.info_instance)
        self.assertEqual(uuids.info_instance, obj.instance_uuid)
        self.assertEqual(nwinfo, obj.network_info)
        mock_get.assert_called_once_with(self.context, uuids.info_instance)

    @mock.patch.object(db, 'instance_info_cache_get', return_value=None)
    def test_get_by_instance_uuid_no_entries(self, mock_get):
        self.assertRaises(
                exception.InstanceInfoCacheNotFound,
                instance_info_cache.InstanceInfoCache.get_by_instance_uuid,
                self.context, uuids.info_instance)
        mock_get.assert_called_once_with(self.context, uuids.info_instance)

    def test_new(self):
        obj = instance_info_cache.InstanceInfoCache.new(self.context,
                                                        uuids.info_instance)
        self.assertEqual(set(['instance_uuid', 'network_info']),
                         obj.obj_what_changed())
        self.assertEqual(uuids.info_instance, obj.instance_uuid)
        self.assertIsNone(obj.network_info)

    @mock.patch.object(cells_opts, 'get_cell_type')
    @mock.patch.object(cells_rpcapi, 'CellsAPI')
    @mock.patch.object(db, 'instance_info_cache_update')
    def _save_helper(self, cell_type, update_cells, mock_update,
                     mock_rpc, mock_get_type):
        obj = instance_info_cache.InstanceInfoCache()
        cells_api = cells_rpcapi.CellsAPI()

        nwinfo = network_model.NetworkInfo.hydrate([{'address': 'foo'}])
        new_info_cache = fake_info_cache.copy()
        new_info_cache['network_info'] = nwinfo.json()
        mock_update.return_value = new_info_cache
        with mock.patch.object(cells_api,
                               'instance_info_cache_update_at_top'):
            if update_cells:
                mock_get_type.return_vaule = cell_type
                if cell_type == 'compute':
                    mock_rpc.return_value = cells_api
                    cells_api.instance_info_cache_update_at_top(
                        self.context, 'foo')
                mock_rpc.assert_called_once_with()
        obj._context = self.context
        obj.instance_uuid = uuids.info_instance
        obj.network_info = nwinfo
        obj.save(update_cells=update_cells)
        mock_update.asssert_called_once_with(self.context, obj.instance_uuid,
                                             {'network_info': nwinfo.json()})
        if update_cells:
            mock_get_type.assert_called_once()

    def test_save_with_update_cells_and_compute_cell(self):
        self._save_helper('compute', True)

    def test_save_with_update_cells_and_non_compute_cell(self):
        self._save_helper(None, True)

    def test_save_without_update_cells(self):
        self._save_helper(None, False)

    @mock.patch.object(db, 'instance_info_cache_update')
    def test_save_updates_self(self, mock_update):
        fake_updated_at = datetime.datetime(2015, 1, 1)
        nwinfo = network_model.NetworkInfo.hydrate([{'address': 'foo'}])
        nwinfo_json = nwinfo.json()
        new_info_cache = fake_info_cache.copy()
        new_info_cache['id'] = 1
        new_info_cache['updated_at'] = fake_updated_at
        new_info_cache['network_info'] = nwinfo_json
        mock_update.return_value = new_info_cache
        obj = instance_info_cache.InstanceInfoCache(context=self.context)
        obj.instance_uuid = uuids.info_instance
        obj.network_info = nwinfo_json
        obj.save()
        mock_update.assert_called_once_with(self.context, uuids.info_instance,
                                            {'network_info': nwinfo_json})
        self.assertEqual(timeutils.normalize_time(fake_updated_at),
                         timeutils.normalize_time(obj.updated_at))

    @mock.patch.object(db, 'instance_info_cache_get',
                       return_value=fake_info_cache)
    def test_refresh(self, mock_get):
        obj = instance_info_cache.InstanceInfoCache.new(self.context,
                                                        uuids.info_instance_1)
        obj.refresh()
        self.assertEqual(fake_info_cache['instance_uuid'], obj.instance_uuid)
        mock_get.assert_called_once_with(self.context, uuids.info_instance_1)


class TestInstanceInfoCacheObject(test_objects._LocalTest,
                                  _TestInstanceInfoCacheObject):
    pass


class TestInstanceInfoCacheObjectRemote(test_objects._RemoteTest,
                                        _TestInstanceInfoCacheObject):
    pass
