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

from nova import db
from nova.objects import base
from nova.objects import utils


class InstanceInfoCache(base.NovaObject):
    fields = {
        'instance_uuid': str,
        'network_info': utils.str_or_none,
        }

    @staticmethod
    def _from_db_object(context, info_cache, db_obj):
        info_cache.instance_uuid = db_obj['instance_uuid']
        info_cache.network_info = db_obj['network_info']
        info_cache.obj_reset_changes()
        info_cache._context = context
        return info_cache

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        db_obj = db.instance_info_cache_get(context, instance_uuid)
        return InstanceInfoCache._from_db_object(context, cls(), db_obj)

    @base.remotable
    def save(self, context):
        if 'network_info' in self.obj_what_changed():
            db.instance_info_cache_update(context, self.instance_uuid,
                                          {'network_info': self.network_info})
            self.obj_reset_changes()
