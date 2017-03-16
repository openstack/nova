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

"""Implementation of a fake volume API."""

from oslo_log import log as logging
from oslo_utils import timeutils

import nova.conf
from nova import exception
from nova.tests import uuidsentinel as uuids


LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


class fake_volume(object):
    user_uuid = '4a3cd440-b9c2-11e1-afa6-0800200c9a66'
    instance_uuid = '4a3cd441-b9c2-11e1-afa6-0800200c9a66'

    def __init__(self, size, name,
                 description, volume_id, snapshot,
                 volume_type, metadata,
                 availability_zone):
        snapshot_id = None
        if snapshot is not None:
            snapshot_id = snapshot['id']
        if volume_id is None:
            volume_id = uuids.fake1
        self.vol = {
            'created_at': timeutils.utcnow(),
            'deleted_at': None,
            'updated_at': timeutils.utcnow(),
            'uuid': 'WTF',
            'deleted': False,
            'id': volume_id,
            'user_id': self.user_uuid,
            'project_id': 'fake-project-id',
            'snapshot_id': snapshot_id,
            'host': None,
            'size': size,
            'availability_zone': availability_zone,
            'instance_uuid': None,
            'mountpoint': None,
            'attach_time': timeutils.utcnow(),
            'status': 'available',
            'attach_status': 'detached',
            'scheduled_at': None,
            'launched_at': None,
            'terminated_at': None,
            'display_name': name,
            'display_description': description,
            'provider_location': 'fake-location',
            'provider_auth': 'fake-auth',
            'volume_type_id': 99,
            'multiattach': False
            }

    def get(self, key, default=None):
        return self.vol[key]

    def __setitem__(self, key, value):
        self.vol[key] = value

    def __getitem__(self, key):
        return self.vol[key]


class fake_snapshot(object):
    user_uuid = '4a3cd440-b9c2-11e1-afa6-0800200c9a66'
    instance_uuid = '4a3cd441-b9c2-11e1-afa6-0800200c9a66'

    def __init__(self, volume_id, size, name, desc, id=None):
        if id is None:
            id = uuids.fake2
        self.snap = {
            'created_at': timeutils.utcnow(),
            'deleted_at': None,
            'updated_at': timeutils.utcnow(),
            'uuid': 'WTF',
            'deleted': False,
            'id': str(id),
            'volume_id': volume_id,
            'status': 'available',
            'progress': '100%',
            'volume_size': 1,
            'display_name': name,
            'display_description': desc,
            'user_id': self.user_uuid,
            'project_id': 'fake-project-id'
            }

    def get(self, key, default=None):
        return self.snap[key]

    def __setitem__(self, key, value):
        self.snap[key] = value

    def __getitem__(self, key):
        return self.snap[key]


class API(object):
    volume_list = []
    snapshot_list = []
    _instance = None

    class Singleton(object):
        def __init__(self):
            self.API = None

    def __init__(self):
        if API._instance is None:
            API._instance = API.Singleton()

        self._EventHandler_instance = API._instance

    def create(self, context, size, name, description, snapshot=None,
               volume_type=None, metadata=None, availability_zone=None):
        v = fake_volume(size, name,
                        description, None,
                        snapshot, volume_type,
                        metadata, availability_zone)
        self.volume_list.append(v.vol)
        LOG.info('creating volume %s', v.vol['id'])
        return v.vol

    def create_with_kwargs(self, context, **kwargs):
        volume_id = kwargs.get('volume_id', None)
        v = fake_volume(kwargs['size'],
                        kwargs['name'],
                        kwargs['description'],
                        str(volume_id),
                        None,
                        None,
                        None,
                        None)
        if kwargs.get('status', None) is not None:
            v.vol['status'] = kwargs['status']
        if kwargs['host'] is not None:
            v.vol['host'] = kwargs['host']
        if kwargs['attach_status'] is not None:
            v.vol['attach_status'] = kwargs['attach_status']
        if kwargs.get('snapshot_id', None) is not None:
            v.vol['snapshot_id'] = kwargs['snapshot_id']

        self.volume_list.append(v.vol)
        return v.vol

    def get(self, context, volume_id):
        if str(volume_id) == '87654321':
            return {'id': volume_id,
                    'attach_time': '13:56:24',
                    'attach_status': 'attached',
                    'status': 'in-use'}

        for v in self.volume_list:
            if v['id'] == str(volume_id):
                return v

        raise exception.VolumeNotFound(volume_id=volume_id)

    def get_all(self, context):
        return self.volume_list

    def delete(self, context, volume_id):
        LOG.info('deleting volume %s', volume_id)
        self.volume_list = [v for v in self.volume_list
                            if v['id'] != volume_id]

    def check_availability_zone(self, context, volume, instance=None):
        if instance and not CONF.cinder.cross_az_attach:
            if instance['availability_zone'] != volume['availability_zone']:
                msg = "Instance and volume not in same availability_zone"
                raise exception.InvalidVolume(reason=msg)

    def attach(self, context, volume_id, instance_uuid, mountpoint, mode='rw'):
        LOG.info('attaching volume %s', volume_id)
        volume = self.get(context, volume_id)
        volume['status'] = 'in-use'
        volume['attach_status'] = 'attached'
        volume['attach_time'] = timeutils.utcnow()
        volume['multiattach'] = True
        volume['attachments'] = {instance_uuid:
                                 {'attachment_id': uuids.fake3,
                                  'mountpoint': mountpoint}}

    def reset_fake_api(self, context):
        del self.volume_list[:]
        del self.snapshot_list[:]

    def detach(self, context, volume_id, instance_uuid, attachment_id=None):
        LOG.info('detaching volume %s', volume_id)
        volume = self.get(context, volume_id)
        volume['status'] = 'available'
        volume['attach_status'] = 'detached'

    def initialize_connection(self, context, volume_id, connector):
        return {'driver_volume_type': 'iscsi', 'data': {}}

    def terminate_connection(self, context, volume_id, connector):
        return None

    def get_snapshot(self, context, snapshot_id):
        for snap in self.snapshot_list:
            if snap['id'] == str(snapshot_id):
                return snap

    def get_all_snapshots(self, context):
        return self.snapshot_list

    def create_snapshot(self, context, volume_id, name, description, id=None):
        volume = self.get(context, volume_id)
        snapshot = fake_snapshot(volume['id'], volume['size'],
                                 name, description, id)
        self.snapshot_list.append(snapshot.snap)
        return snapshot.snap

    def create_snapshot_with_kwargs(self, context, **kwargs):
        snapshot = fake_snapshot(kwargs.get('volume_id'),
                                 kwargs.get('volume_size'),
                                 kwargs.get('name'),
                                 kwargs.get('description'),
                                 kwargs.get('snap_id'))

        status = kwargs.get('status', None)
        snapshot.snap['status'] = status
        self.snapshot_list.append(snapshot.snap)
        return snapshot.snap

    def create_snapshot_force(self, context, volume_id,
                              name, description, id=None):
        volume = self.get(context, volume_id)
        snapshot = fake_snapshot(volume['id'], volume['size'],
                                 name, description, id)
        self.snapshot_list.append(snapshot.snap)
        return snapshot.snap

    def delete_snapshot(self, context, snapshot_id):
        self.snapshot_list = [s for s in self.snapshot_list
                              if s['id'] != snapshot_id]

    def reserve_volume(self, context, volume_id):
        LOG.info('reserving volume %s', volume_id)
        volume = self.get(context, volume_id)
        volume['status'] = 'attaching'

    def unreserve_volume(self, context, volume_id):
        LOG.info('unreserving volume %s', volume_id)
        volume = self.get(context, volume_id)
        volume['status'] = 'available'

    def begin_detaching(self, context, volume_id):
        LOG.info('begin detaching volume %s', volume_id)
        volume = self.get(context, volume_id)
        volume['status'] = 'detaching'

    def roll_detaching(self, context, volume_id):
        LOG.info('roll detaching volume %s', volume_id)
        volume = self.get(context, volume_id)
        volume['status'] = 'in-use'
