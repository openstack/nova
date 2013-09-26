# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 OpenStack Foundation
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
from nova import exception
from nova.objects import base
from nova.objects import utils as obj_utils


class InstanceGroup(base.NovaPersistentObject, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: String attributes updated to support unicode
    # Version 1.2: Use list/dict helpers for policies, metadetails, members
    # Version 1.3: Make uuid a non-None real string
    VERSION = '1.3'

    fields = {
        'id': int,

        'user_id': obj_utils.str_or_none,
        'project_id': obj_utils.str_or_none,

        'uuid': obj_utils.cstring,
        'name': obj_utils.str_or_none,

        'policies': obj_utils.list_of_strings_or_none,
        'metadetails': obj_utils.dict_of_strings_or_none,
        'members': obj_utils.list_of_strings_or_none,
        }

    @staticmethod
    def _from_db_object(context, instance_group, db_inst):
        """Method to help with migration to objects.

        Converts a database entity to a formal object.
        """
        # Most of the field names match right now, so be quick
        for field in instance_group.fields:
            if field == 'deleted':
                instance_group.deleted = db_inst['deleted'] == db_inst['id']
            else:
                instance_group[field] = db_inst[field]

        instance_group._context = context
        instance_group.obj_reset_changes()
        return instance_group

    @base.remotable_classmethod
    def get_by_uuid(cls, context, uuid):
        db_inst = db.instance_group_get(context, uuid)
        return cls._from_db_object(context, cls(), db_inst)

    @base.remotable
    def save(self, context):
        """Save updates to this instance group."""

        updates = self.obj_get_changes()
        if not updates:
            return

        metadata = None
        if 'metadetails' in updates:
            metadata = updates.pop('metadetails')
            updates.update({'metadata': metadata})

        db.instance_group_update(context, self.uuid, updates)
        db_inst = db.instance_group_get(context, self.uuid)
        self._from_db_object(context, self, db_inst)

    @base.remotable
    def refresh(self, context):
        """Refreshes the instance group."""
        current = self.__class__.get_by_uuid(context, self.uuid)
        for field in self.fields:
            if self.obj_attr_is_set(field) and self[field] != current[field]:
                self[field] = current[field]
        self.obj_reset_changes()

    @base.remotable
    def create(self, context):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        updates = self.obj_get_changes()
        updates.pop('id', None)
        policies = updates.pop('policies', None)
        members = updates.pop('members', None)
        metadetails = updates.pop('metadetails', None)

        db_inst = db.instance_group_create(context, updates,
                                           policies=policies,
                                           metadata=metadetails,
                                           members=members)
        self._from_db_object(context, self, db_inst)

    @base.remotable
    def destroy(self, context):
        db.instance_group_delete(context, self.uuid)
        self.obj_reset_changes()


def _make_instance_group_list(context, inst_list, db_list):
    inst_list.objects = []
    for group in db_list:
        inst_obj = InstanceGroup._from_db_object(context, InstanceGroup(),
                                                 group)
        inst_list.objects.append(inst_obj)
    inst_list.obj_reset_changes()
    return inst_list


class InstanceGroupList(base.ObjectListBase, base.NovaObject):

    @base.remotable_classmethod
    def get_by_project_id(cls, context, project_id):
        groups = db.instance_group_get_all_by_project_id(context, project_id)
        return _make_instance_group_list(context, cls(), groups)

    @base.remotable_classmethod
    def get_all(cls, context):
        groups = db.instance_group_get_all(context)
        return _make_instance_group_list(context, cls(), groups)
