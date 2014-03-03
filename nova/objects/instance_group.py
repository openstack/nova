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
from nova.objects import fields


class InstanceGroup(base.NovaPersistentObject, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: String attributes updated to support unicode
    # Version 1.2: Use list/dict helpers for policies, metadetails, members
    # Version 1.3: Make uuid a non-None real string
    # Version 1.4: Add add_members()
    VERSION = '1.4'

    fields = {
        'id': fields.IntegerField(),

        'user_id': fields.StringField(nullable=True),
        'project_id': fields.StringField(nullable=True),

        'uuid': fields.UUIDField(),
        'name': fields.StringField(nullable=True),

        'policies': fields.ListOfStringsField(nullable=True),
        'metadetails': fields.DictOfStringsField(nullable=True),
        'members': fields.ListOfStringsField(nullable=True),
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

    @base.remotable_classmethod
    def add_members(cls, context, group_uuid, instance_uuids):
        members = db.instance_group_members_add(context, group_uuid,
                instance_uuids)
        return list(members)


class InstanceGroupList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    #              InstanceGroup <= version 1.3
    # Version 1.1: InstanceGroup <= version 1.4
    VERSION = '1.1'

    fields = {
        'objects': fields.ListOfObjectsField('InstanceGroup'),
        }
    child_versions = {
        '1.0': '1.3',
        # NOTE(danms): InstanceGroup was at 1.3 before we added this
        '1.1': '1.4',
        }

    @base.remotable_classmethod
    def get_by_project_id(cls, context, project_id):
        groups = db.instance_group_get_all_by_project_id(context, project_id)
        return base.obj_make_list(context, InstanceGroupList(), InstanceGroup,
                                  groups)

    @base.remotable_classmethod
    def get_all(cls, context):
        groups = db.instance_group_get_all(context)
        return base.obj_make_list(context, InstanceGroupList(), InstanceGroup,
                                  groups)
