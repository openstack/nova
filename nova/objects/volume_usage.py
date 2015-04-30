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

from nova import db
from nova.objects import base
from nova.objects import fields


@base.NovaObjectRegistry.register
class VolumeUsage(base.NovaPersistentObject, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'volume_id': fields.UUIDField(),
        'instance_uuid': fields.UUIDField(nullable=True),
        'project_id': fields.StringField(nullable=True),
        'user_id': fields.StringField(nullable=True),
        'availability_zone': fields.StringField(nullable=True),
        'tot_last_refreshed': fields.DateTimeField(nullable=True,
                                                   read_only=True),
        'tot_reads': fields.IntegerField(read_only=True),
        'tot_read_bytes': fields.IntegerField(read_only=True),
        'tot_writes': fields.IntegerField(read_only=True),
        'tot_write_bytes': fields.IntegerField(read_only=True),
        'curr_last_refreshed': fields.DateTimeField(nullable=True,
                                                    read_only=True),
        'curr_reads': fields.IntegerField(),
        'curr_read_bytes': fields.IntegerField(),
        'curr_writes': fields.IntegerField(),
        'curr_write_bytes': fields.IntegerField()
    }

    @staticmethod
    def _from_db_object(context, vol_usage, db_vol_usage):
        for field in vol_usage.fields:
            setattr(vol_usage, field, db_vol_usage[field])
        vol_usage._context = context
        vol_usage.obj_reset_changes()
        return vol_usage

    @base.remotable
    def save(self, update_totals=False):
        db_vol_usage = db.vol_usage_update(
            self._context, self.volume_id, self.curr_reads,
            self.curr_read_bytes, self.curr_writes, self.curr_write_bytes,
            self.instance_uuid, self.project_id, self.user_id,
            self.availability_zone, update_totals=update_totals)
        self._from_db_object(self._context, self, db_vol_usage)
