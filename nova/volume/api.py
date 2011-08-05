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

    def create(self, context, size, snapshot_id, name, description):
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

        options = {
            'size': size,
            'user_id': context.user_id,
            'project_id': context.project_id,
            'snapshot_id': snapshot_id,
            'availability_zone': FLAGS.storage_availability_zone,
            'status': "creating",
            'attach_status': "detached",
            'display_name': name,
            'display_description': description}

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

    def get_all(self, context):
        if context.is_admin:
            return self.db.volume_get_all(context)
        return self.db.volume_get_all_by_project(context, context.project_id)

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
