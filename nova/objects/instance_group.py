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
from nova import objects
from nova.objects import base
from nova.objects import fields
from nova.openstack.common import uuidutils


class InstanceGroup(base.NovaPersistentObject, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: String attributes updated to support unicode
    # Version 1.2: Use list/dict helpers for policies, metadetails, members
    # Version 1.3: Make uuid a non-None real string
    # Version 1.4: Add add_members()
    # Version 1.5: Add get_hosts()
    # Version 1.6: Add get_by_name()
    # Version 1.7: Deprecate metadetails
    VERSION = '1.7'

    fields = {
        'id': fields.IntegerField(),

        'user_id': fields.StringField(nullable=True),
        'project_id': fields.StringField(nullable=True),

        'uuid': fields.UUIDField(),
        'name': fields.StringField(nullable=True),

        'policies': fields.ListOfStringsField(nullable=True),
        'members': fields.ListOfStringsField(nullable=True),
        }

    def obj_make_compatible(self, primitive, target_version):
        if target_version < (1, 7):
            # NOTE(danms): Before 1.7, we had an always-empty
            # metadetails property
            primitive['metadetails'] = {}

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

    @base.remotable_classmethod
    def get_by_name(cls, context, name):
        # TODO(russellb) We need to get the group by name here.  There's no
        # db.api method for this yet.  Come back and optimize this by
        # adding a new query by name.  This is unnecessarily expensive if a
        # tenant has lots of groups.
        igs = objects.InstanceGroupList.get_by_project_id(context,
                                                          context.project_id)
        for ig in igs:
            if ig.name == name:
                return ig

        raise exception.InstanceGroupNotFound(group_uuid=name)

    @classmethod
    def get_by_hint(cls, context, hint):
        if uuidutils.is_uuid_like(hint):
            return cls.get_by_uuid(context, hint)
        else:
            return cls.get_by_name(context, hint)

    @base.remotable
    def save(self, context):
        """Save updates to this instance group."""

        updates = self.obj_get_changes()
        if not updates:
            return

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

        db_inst = db.instance_group_create(context, updates,
                                           policies=policies,
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

    @base.remotable
    def get_hosts(self, context, exclude=None):
        """Get a list of hosts for non-deleted instances in the group

        This method allows you to get a list of the hosts where instances in
        this group are currently running.  There's also an option to exclude
        certain instance UUIDs from this calculation.

        """
        filter_uuids = self.members
        if exclude:
            filter_uuids = set(filter_uuids) - set(exclude)
        filters = {'uuid': filter_uuids, 'deleted': False}
        instances = objects.InstanceList.get_by_filters(context,
                                                        filters=filters)
        return list(set([instance.host for instance in instances
                         if instance.host]))


class InstanceGroupList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    #              InstanceGroup <= version 1.3
    # Version 1.1: InstanceGroup <= version 1.4
    # Version 1.2: InstanceGroup <= version 1.5
    # Version 1.3: InstanceGroup <= version 1.6
    # Version 1.4: InstanceGroup <= version 1.7
    VERSION = '1.2'

    fields = {
        'objects': fields.ListOfObjectsField('InstanceGroup'),
        }
    child_versions = {
        '1.0': '1.3',
        # NOTE(danms): InstanceGroup was at 1.3 before we added this
        '1.1': '1.4',
        '1.2': '1.5',
        '1.3': '1.6',
        '1.4': '1.7',
        }

    @base.remotable_classmethod
    def get_by_project_id(cls, context, project_id):
        groups = db.instance_group_get_all_by_project_id(context, project_id)
        return base.obj_make_list(context, cls(context), objects.InstanceGroup,
                                  groups)

    @base.remotable_classmethod
    def get_all(cls, context):
        groups = db.instance_group_get_all(context)
        return base.obj_make_list(context, cls(context), objects.InstanceGroup,
                                  groups)
