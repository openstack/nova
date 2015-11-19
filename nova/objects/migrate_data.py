#    Copyright 2015 Red Hat, Inc.
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

from nova.objects import base as obj_base
from nova.objects import fields


@obj_base.NovaObjectRegistry.register_if(False)
class LiveMigrateData(obj_base.NovaObject):
    fields = {
        'is_volume_backed': fields.BooleanField(),
        'migration': fields.ObjectField('Migration'),
    }

    def to_legacy_dict(self, pre_migration_result=False):
        legacy = {}
        if self.obj_attr_is_set('is_volume_backed'):
            legacy['is_volume_backed'] = self.is_volume_backed
        if self.obj_attr_is_set('migration'):
            legacy['migration'] = self.migration
        if pre_migration_result:
            legacy['pre_live_migration_result'] = {}

        return legacy

    def from_legacy_dict(self, legacy):
        if 'is_volume_backed' in legacy:
            self.is_volume_backed = legacy['is_volume_backed']
        if 'migration' in legacy:
            self.migration = legacy['migration']
