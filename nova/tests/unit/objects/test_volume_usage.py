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
from oslo_utils import timeutils

from nova import objects
from nova.tests.unit.objects import test_objects
from nova.tests import uuidsentinel as uuids


NOW = timeutils.utcnow().replace(microsecond=0)

fake_vol_usage = {
    'created_at': NOW,
    'updated_at': None,
    'deleted_at': None,
    'deleted': 0,
    'id': 1,
    'volume_id': uuids.volume_id,
    'instance_uuid': uuids.instance,
    'project_id': 'fake-project-id',
    'user_id': 'fake-user-id',
    'availability_zone': None,
    'tot_last_refreshed': None,
    'tot_reads': 0,
    'tot_read_bytes': 0,
    'tot_writes': 0,
    'tot_write_bytes': 0,
    'curr_last_refreshed': NOW,
    'curr_reads': 10,
    'curr_read_bytes': 20,
    'curr_writes': 30,
    'curr_write_bytes': 40,
    }


class _TestVolumeUsage(object):
    @mock.patch('nova.db.api.vol_usage_update', return_value=fake_vol_usage)
    def test_save(self, mock_upd):
        vol_usage = objects.VolumeUsage(self.context)
        vol_usage.volume_id = uuids.volume_id
        vol_usage.instance_uuid = uuids.instance
        vol_usage.project_id = 'fake-project-id'
        vol_usage.user_id = 'fake-user-id'
        vol_usage.availability_zone = None
        vol_usage.curr_reads = 10
        vol_usage.curr_read_bytes = 20
        vol_usage.curr_writes = 30
        vol_usage.curr_write_bytes = 40
        vol_usage.save()
        mock_upd.assert_called_once_with(
            self.context, uuids.volume_id, 10, 20, 30, 40, uuids.instance,
            'fake-project-id', 'fake-user-id', None, update_totals=False)
        self.compare_obj(vol_usage, fake_vol_usage)

    @mock.patch('nova.db.api.vol_usage_update', return_value=fake_vol_usage)
    def test_save_update_totals(self, mock_upd):
        vol_usage = objects.VolumeUsage(self.context)
        vol_usage.volume_id = uuids.volume_id
        vol_usage.instance_uuid = uuids.instance
        vol_usage.project_id = 'fake-project-id'
        vol_usage.user_id = 'fake-user-id'
        vol_usage.availability_zone = None
        vol_usage.curr_reads = 10
        vol_usage.curr_read_bytes = 20
        vol_usage.curr_writes = 30
        vol_usage.curr_write_bytes = 40
        vol_usage.save(update_totals=True)
        mock_upd.assert_called_once_with(
            self.context, uuids.volume_id, 10, 20, 30, 40, uuids.instance,
            'fake-project-id', 'fake-user-id', None, update_totals=True)
        self.compare_obj(vol_usage, fake_vol_usage)


class TestVolumeUsage(test_objects._LocalTest, _TestVolumeUsage):
    pass


class TestRemoteVolumeUsage(test_objects._RemoteTest, _TestVolumeUsage):
    pass
