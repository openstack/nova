# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
Handles all requests relating to volumes.
"""

import functools

from eventlet import greenthread

from nova.db import base
from nova import exception
from nova import flags
from nova import log as logging
import nova.policy
from nova import quota
from nova import rpc
from nova import utils

FLAGS = flags.FLAGS
flags.DECLARE('storage_availability_zone', 'nova.volume.manager')

LOG = logging.getLogger(__name__)

QUOTAS = quota.QUOTAS


def wrap_check_policy(func):
    """Check policy corresponding to the wrapped methods prior to execution

    This decorator requires the first 3 args of the wrapped function
    to be (self, context, volume)
    """
    @functools.wraps(func)
    def wrapped(self, context, target_obj, *args, **kwargs):
        check_policy(context, func.__name__, target_obj)
        return func(self, context, target_obj, *args, **kwargs)

    return wrapped


def check_policy(context, action, target_obj=None):
    target = {
        'project_id': context.project_id,
        'user_id': context.user_id,
    }
    target.update(target_obj or {})
    _action = 'volume:%s' % action
    nova.policy.enforce(context, _action, target)


class API(base.Base):
    """API for interacting with the volume manager."""

    def create(self, context, size, name, description, snapshot=None,
                     volume_type=None, metadata=None, availability_zone=None):
        check_policy(context, 'create')
        if snapshot is not None:
            if snapshot['status'] != "available":
                msg = _("status must be available")
                raise exception.InvalidSnapshot(reason=msg)
            if not size:
                size = snapshot['volume_size']

            snapshot_id = snapshot['id']
        else:
            snapshot_id = None

        try:
            reservations = QUOTAS.reserve(context, volumes=1, gigabytes=size)
        except exception.OverQuota:
            pid = context.project_id
            LOG.warn(_("Quota exceeded for %(pid)s, tried to create"
                    " %(size)sG volume") % locals())
            raise exception.VolumeSizeTooLarge()

        if availability_zone is None:
            availability_zone = FLAGS.storage_availability_zone

        if volume_type is None:
            volume_type_id = None
        else:
            volume_type_id = volume_type.get('id', None)

        options = {
            'size': size,
            'user_id': context.user_id,
            'project_id': context.project_id,
            'snapshot_id': snapshot_id,
            'availability_zone': availability_zone,
            'status': "creating",
            'attach_status': "detached",
            'display_name': name,
            'display_description': description,
            'volume_type_id': volume_type_id,
            'metadata': metadata,
            }

        volume = self.db.volume_create(context, options)
        rpc.cast(context,
                 FLAGS.scheduler_topic,
                 {"method": "create_volume",
                  "args": {"topic": FLAGS.volume_topic,
                           "volume_id": volume['id'],
                           "snapshot_id": snapshot_id,
                           "reservations": reservations}})
        return volume

    # TODO(yamahata): eliminate dumb polling
    def wait_creation(self, context, volume):
        volume_id = volume['id']
        while True:
            volume = self.get(context, volume_id)
            if volume['status'] != 'creating':
                return
            greenthread.sleep(1)

    @wrap_check_policy
    def delete(self, context, volume):
        volume_id = volume['id']
        if not volume['host']:
            # NOTE(vish): scheduling failed, so delete it
            self.db.volume_destroy(context, volume_id)
            return
        if volume['status'] not in ["available", "error"]:
            msg = _("Volume status must be available or error")
            raise exception.InvalidVolume(reason=msg)

        snapshots = self.db.snapshot_get_all_for_volume(context, volume_id)
        if len(snapshots):
            msg = _("Volume still has %d dependent snapshots") % len(snapshots)
            raise exception.InvalidVolume(reason=msg)

        now = utils.utcnow()
        self.db.volume_update(context, volume_id, {'status': 'deleting',
                                                   'terminated_at': now})
        host = volume['host']
        rpc.cast(context,
                 rpc.queue_get_for(context, FLAGS.volume_topic, host),
                 {"method": "delete_volume",
                  "args": {"volume_id": volume_id}})

    @wrap_check_policy
    def update(self, context, volume, fields):
        self.db.volume_update(context, volume['id'], fields)

    def get(self, context, volume_id):
        rv = self.db.volume_get(context, volume_id)
        volume = dict(rv.iteritems())
        check_policy(context, 'get', volume)
        return volume

    def get_all(self, context, search_opts={}):
        check_policy(context, 'get_all')
        if context.is_admin:
            volumes = self.db.volume_get_all(context)
        else:
            volumes = self.db.volume_get_all_by_project(context,
                                    context.project_id)

        if search_opts:
            LOG.debug(_("Searching by: %s") % str(search_opts))

            def _check_metadata_match(volume, searchdict):
                volume_metadata = {}
                for i in volume.get('volume_metadata'):
                    volume_metadata[i['key']] = i['value']

                for k, v in searchdict.iteritems():
                    if (k not in volume_metadata.keys() or
                        volume_metadata[k] != v):
                        return False
                return True

            # search_option to filter_name mapping.
            filter_mapping = {'metadata': _check_metadata_match}

            result = []
            for volume in volumes:
                # go over all filters in the list
                for opt, values in search_opts.iteritems():
                    try:
                        filter_func = filter_mapping[opt]
                    except KeyError:
                        # no such filter - ignore it, go to next filter
                        continue
                    else:
                        if filter_func(volume, values):
                            result.append(volume)
                            break
            volumes = result
        return volumes

    def get_snapshot(self, context, snapshot_id):
        check_policy(context, 'get_snapshot')
        rv = self.db.snapshot_get(context, snapshot_id)
        return dict(rv.iteritems())

    def get_all_snapshots(self, context):
        check_policy(context, 'get_all_snapshots')
        if context.is_admin:
            return self.db.snapshot_get_all(context)
        return self.db.snapshot_get_all_by_project(context, context.project_id)

    @wrap_check_policy
    def check_attach(self, context, volume):
        # TODO(vish): abstract status checking?
        if volume['status'] != "available":
            msg = _("status must be available")
            raise exception.InvalidVolume(reason=msg)
        if volume['attach_status'] == "attached":
            msg = _("already attached")
            raise exception.InvalidVolume(reason=msg)

    @wrap_check_policy
    def check_detach(self, context, volume):
        # TODO(vish): abstract status checking?
        if volume['status'] == "available":
            msg = _("already detached")
            raise exception.InvalidVolume(reason=msg)

    def remove_from_compute(self, context, volume, instance_id, host):
        """Remove volume from specified compute host."""
        rpc.call(context,
                 rpc.queue_get_for(context, FLAGS.compute_topic, host),
                 {"method": "remove_volume_connection",
                  "args": {'instance_id': instance_id,
                           'volume_id': volume['id']}})

    @wrap_check_policy
    def reserve_volume(self, context, volume):
        self.update(context, volume, {"status": "attaching"})

    @wrap_check_policy
    def unreserve_volume(self, context, volume):
        if volume['status'] == "attaching":
            self.update(context, volume, {"status": "available"})

    @wrap_check_policy
    def attach(self, context, volume, instance_uuid, mountpoint):
        host = volume['host']
        queue = rpc.queue_get_for(context, FLAGS.volume_topic, host)
        return rpc.call(context, queue,
                        {"method": "attach_volume",
                         "args": {"volume_id": volume['id'],
                                  "instance_uuid": instance_uuid,
                                  "mountpoint": mountpoint}})

    @wrap_check_policy
    def detach(self, context, volume):
        host = volume['host']
        queue = rpc.queue_get_for(context, FLAGS.volume_topic, host)
        return rpc.call(context, queue,
                 {"method": "detach_volume",
                  "args": {"volume_id": volume['id']}})

    @wrap_check_policy
    def initialize_connection(self, context, volume, connector):
        host = volume['host']
        queue = rpc.queue_get_for(context, FLAGS.volume_topic, host)
        return rpc.call(context, queue,
                        {"method": "initialize_connection",
                         "args": {"volume_id": volume['id'],
                                  "connector": connector}})

    @wrap_check_policy
    def terminate_connection(self, context, volume, connector):
        self.unreserve_volume(context, volume)
        host = volume['host']
        queue = rpc.queue_get_for(context, FLAGS.volume_topic, host)
        return rpc.call(context, queue,
                        {"method": "terminate_connection",
                         "args": {"volume_id": volume['id'],
                                  "connector": connector}})

    def _create_snapshot(self, context, volume, name, description,
                         force=False):
        check_policy(context, 'create_snapshot', volume)

        if ((not force) and (volume['status'] != "available")):
            msg = _("must be available")
            raise exception.InvalidVolume(reason=msg)

        options = {
            'volume_id': volume['id'],
            'user_id': context.user_id,
            'project_id': context.project_id,
            'status': "creating",
            'progress': '0%',
            'volume_size': volume['size'],
            'display_name': name,
            'display_description': description}

        snapshot = self.db.snapshot_create(context, options)
        host = volume['host']
        rpc.cast(context,
                 rpc.queue_get_for(context, FLAGS.volume_topic, host),
                 {"method": "create_snapshot",
                  "args": {"volume_id": volume['id'],
                           "snapshot_id": snapshot['id']}})
        return snapshot

    def create_snapshot(self, context, volume, name, description):
        return self._create_snapshot(context, volume, name, description,
                                     False)

    def create_snapshot_force(self, context, volume, name, description):
        return self._create_snapshot(context, volume, name, description,
                                     True)

    @wrap_check_policy
    def delete_snapshot(self, context, snapshot):
        if snapshot['status'] not in ["available", "error"]:
            msg = _("Volume Snapshot status must be available or error")
            raise exception.InvalidVolume(reason=msg)
        self.db.snapshot_update(context, snapshot['id'],
                                {'status': 'deleting'})
        volume = self.db.volume_get(context, snapshot['volume_id'])
        host = volume['host']
        rpc.cast(context,
                 rpc.queue_get_for(context, FLAGS.volume_topic, host),
                 {"method": "delete_snapshot",
                  "args": {"snapshot_id": snapshot['id']}})

    @wrap_check_policy
    def get_volume_metadata(self, context, volume):
        """Get all metadata associated with a volume."""
        rv = self.db.volume_metadata_get(context, volume['id'])
        return dict(rv.iteritems())

    @wrap_check_policy
    def delete_volume_metadata(self, context, volume, key):
        """Delete the given metadata item from a volume."""
        self.db.volume_metadata_delete(context, volume['id'], key)

    @wrap_check_policy
    def update_volume_metadata(self, context, volume, metadata, delete=False):
        """Updates or creates volume metadata.

        If delete is True, metadata items that are not specified in the
        `metadata` argument will be deleted.

        """
        if delete:
            _metadata = metadata
        else:
            _metadata = self.get_volume_metadata(context, volume['id'])
            _metadata.update(metadata)

        self.db.volume_metadata_update(context, volume['id'], _metadata, True)
        return _metadata

    def get_volume_metadata_value(self, volume, key):
        """Get value of particular metadata key."""
        metadata = volume.get('volume_metadata')
        if metadata:
            for i in volume['volume_metadata']:
                if i['key'] == key:
                    return i['value']
        return None
