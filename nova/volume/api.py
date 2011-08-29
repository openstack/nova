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


from eventlet import greenthread

from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import quota
from nova import rpc
from nova import utils
from nova.db import base

FLAGS = flags.FLAGS
flags.DECLARE('storage_availability_zone', 'nova.volume.manager')

LOG = logging.getLogger('nova.volume')


class API(base.Base):
    """API for interacting with the volume manager."""

    def create(self, context, size, snapshot_id, name, description,
                     volume_type=None, metadata=None, availability_zone=None):
        if snapshot_id != None:
            snapshot = self.get_snapshot(context, snapshot_id)
            if snapshot['status'] != "available":
                raise exception.ApiError(
                    _("Snapshot status must be available"))
            if not size:
                size = snapshot['volume_size']

        if quota.allowed_volumes(context, 1, size) < 1:
            pid = context.project_id
            LOG.warn(_("Quota exceeded for %(pid)s, tried to create"
                    " %(size)sG volume") % locals())
            raise quota.QuotaError(_("Volume quota exceeded. You cannot "
                                     "create a volume of size %sG") % size)

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
                           "snapshot_id": snapshot_id}})
        return volume

    # TODO(yamahata): eliminate dumb polling
    def wait_creation(self, context, volume_id):
        while True:
            volume = self.get(context, volume_id)
            if volume['status'] != 'creating':
                return
            greenthread.sleep(1)

    def delete(self, context, volume_id):
        volume = self.get(context, volume_id)
        if volume['status'] != "available":
            raise exception.ApiError(_("Volume status must be available"))
        now = utils.utcnow()
        self.db.volume_update(context, volume_id, {'status': 'deleting',
                                                   'terminated_at': now})
        host = volume['host']
        rpc.cast(context,
                 self.db.queue_get_for(context, FLAGS.volume_topic, host),
                 {"method": "delete_volume",
                  "args": {"volume_id": volume_id}})

    def update(self, context, volume_id, fields):
        self.db.volume_update(context, volume_id, fields)

    def get(self, context, volume_id):
        rv = self.db.volume_get(context, volume_id)
        return dict(rv.iteritems())

    def get_all(self, context, search_opts={}):
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
                    if k not in volume_metadata.keys()\
                       or volume_metadata[k] != v:
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
        rv = self.db.snapshot_get(context, snapshot_id)
        return dict(rv.iteritems())

    def get_all_snapshots(self, context):
        if context.is_admin:
            return self.db.snapshot_get_all(context)
        return self.db.snapshot_get_all_by_project(context, context.project_id)

    def check_attach(self, context, volume_id):
        volume = self.get(context, volume_id)
        # TODO(vish): abstract status checking?
        if volume['status'] != "available":
            raise exception.ApiError(_("Volume status must be available"))
        if volume['attach_status'] == "attached":
            raise exception.ApiError(_("Volume is already attached"))

    def check_detach(self, context, volume_id):
        volume = self.get(context, volume_id)
        # TODO(vish): abstract status checking?
        if volume['status'] == "available":
            raise exception.ApiError(_("Volume is already detached"))

    def remove_from_compute(self, context, volume_id, host):
        """Remove volume from specified compute host."""
        rpc.call(context,
                 self.db.queue_get_for(context, FLAGS.compute_topic, host),
                 {"method": "remove_volume",
                  "args": {'volume_id': volume_id}})

    def _create_snapshot(self, context, volume_id, name, description,
                         force=False):
        volume = self.get(context, volume_id)
        if ((not force) and (volume['status'] != "available")):
            raise exception.ApiError(_("Volume status must be available"))

        options = {
            'volume_id': volume_id,
            'user_id': context.user_id,
            'project_id': context.project_id,
            'status': "creating",
            'progress': '0%',
            'volume_size': volume['size'],
            'display_name': name,
            'display_description': description}

        snapshot = self.db.snapshot_create(context, options)
        rpc.cast(context,
                 FLAGS.scheduler_topic,
                 {"method": "create_snapshot",
                  "args": {"topic": FLAGS.volume_topic,
                           "volume_id": volume_id,
                           "snapshot_id": snapshot['id']}})
        return snapshot

    def create_snapshot(self, context, volume_id, name, description):
        return self._create_snapshot(context, volume_id, name, description,
                                     False)

    def create_snapshot_force(self, context, volume_id, name, description):
        return self._create_snapshot(context, volume_id, name, description,
                                     True)

    def delete_snapshot(self, context, snapshot_id):
        snapshot = self.get_snapshot(context, snapshot_id)
        if snapshot['status'] != "available":
            raise exception.ApiError(_("Snapshot status must be available"))
        self.db.snapshot_update(context, snapshot_id, {'status': 'deleting'})
        rpc.cast(context,
                 FLAGS.scheduler_topic,
                 {"method": "delete_snapshot",
                  "args": {"topic": FLAGS.volume_topic,
                           "snapshot_id": snapshot_id}})

    def get_volume_metadata(self, context, volume_id):
        """Get all metadata associated with a volume."""
        rv = self.db.volume_metadata_get(context, volume_id)
        return dict(rv.iteritems())

    def delete_volume_metadata(self, context, volume_id, key):
        """Delete the given metadata item from an volume."""
        self.db.volume_metadata_delete(context, volume_id, key)

    def update_volume_metadata(self, context, volume_id,
                                 metadata, delete=False):
        """Updates or creates volume metadata.

        If delete is True, metadata items that are not specified in the
        `metadata` argument will be deleted.

        """
        if delete:
            _metadata = metadata
        else:
            _metadata = self.get_volume_metadata(context, volume_id)
            _metadata.update(metadata)

        self.db.volume_metadata_update(context, volume_id, _metadata, True)
        return _metadata

    def get_volume_metadata_value(self, volume, key):
        """Get value of particular metadata key."""
        metadata = volume.get('volume_metadata')
        if metadata:
            for i in volume['volume_metadata']:
                if i['key'] == key:
                    return i['value']
        return None
