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

import datetime

from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import quota
from nova import rpc
from nova.db import base

FLAGS = flags.FLAGS
flags.DECLARE('storage_availability_zone', 'nova.volume.manager')

LOG = logging.getLogger('nova.volume')


class API(base.Base):
    """API for interacting with the volume manager."""

    def create(self, context, size, name, description):
        if quota.allowed_volumes(context, 1, size) < 1:
            pid = context.project_id
            LOG.warn(_("Quota exceeeded for %(pid)s, tried to create"
                    " %(size)sG volume") % locals())
            raise quota.QuotaError(_("Volume quota exceeded. You cannot "
                                     "create a volume of size %sG") % size)

        options = {
            'size': size,
            'user_id': context.user_id,
            'project_id': context.project_id,
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
                           "volume_id": volume['id']}})
        return volume

    def delete(self, context, volume_id):
        volume = self.get(context, volume_id)
        if volume['status'] != "available":
            raise exception.ApiError(_("Volume status must be available"))
        now = datetime.datetime.utcnow()
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
