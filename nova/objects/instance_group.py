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

from oslo_utils import uuidutils
from oslo_utils import versionutils

from nova.compute import utils as compute_utils
from nova import db
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields


LAZY_LOAD_FIELDS = ['hosts']


# TODO(berrange): Remove NovaObjectDictCompat
@base.NovaObjectRegistry.register
class InstanceGroup(base.NovaPersistentObject, base.NovaObject,
                    base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: String attributes updated to support unicode
    # Version 1.2: Use list/dict helpers for policies, metadetails, members
    # Version 1.3: Make uuid a non-None real string
    # Version 1.4: Add add_members()
    # Version 1.5: Add get_hosts()
    # Version 1.6: Add get_by_name()
    # Version 1.7: Deprecate metadetails
    # Version 1.8: Add count_members_by_user()
    # Version 1.9: Add get_by_instance_uuid()
    # Version 1.10: Add hosts field
    VERSION = '1.10'

    fields = {
        'id': fields.IntegerField(),

        'user_id': fields.StringField(nullable=True),
        'project_id': fields.StringField(nullable=True),

        'uuid': fields.UUIDField(),
        'name': fields.StringField(nullable=True),

        'policies': fields.ListOfStringsField(nullable=True),
        'members': fields.ListOfStringsField(nullable=True),
        'hosts': fields.ListOfStringsField(nullable=True),
        }

    def obj_make_compatible(self, primitive, target_version):
        target_version = versionutils.convert_version_to_tuple(target_version)
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
            if field in LAZY_LOAD_FIELDS:
                continue
            if field == 'deleted':
                instance_group.deleted = db_inst['deleted'] == db_inst['id']
            else:
                instance_group[field] = db_inst[field]

        instance_group._context = context
        instance_group.obj_reset_changes()
        return instance_group

    def obj_load_attr(self, attrname):
        # NOTE(sbauza): Only hosts could be lazy-loaded right now
        if attrname != 'hosts':
            raise exception.ObjectActionError(
                action='obj_load_attr', reason='unable to load %s' % attrname)

        self.hosts = self.get_hosts()
        self.obj_reset_changes(['hosts'])

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

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        db_inst = db.instance_group_get_by_instance(context, instance_uuid)
        return cls._from_db_object(context, cls(), db_inst)

    @classmethod
    def get_by_hint(cls, context, hint):
        if uuidutils.is_uuid_like(hint):
            return cls.get_by_uuid(context, hint)
        else:
            return cls.get_by_name(context, hint)

    @base.remotable
    def save(self):
        """Save updates to this instance group."""

        updates = self.obj_get_changes()

        # NOTE(sbauza): We do NOT save the set of compute nodes that an
        # instance group is connected to in this method. Instance groups are
        # implicitly connected to compute nodes when the
        # InstanceGroup.add_members() method is called, which adds the mapping
        # table entries.
        # So, since the only way to have hosts in the updates is to set that
        # field explicitly, we prefer to raise an Exception so the developer
        # knows he has to call obj_reset_changes(['hosts']) right after setting
        # the field.
        if 'hosts' in updates:
            raise exception.InstanceGroupSaveException(field='hosts')

        if not updates:
            return

        payload = dict(updates)
        payload['server_group_id'] = self.uuid

        db.instance_group_update(self._context, self.uuid, updates)
        db_inst = db.instance_group_get(self._context, self.uuid)
        self._from_db_object(self._context, self, db_inst)
        compute_utils.notify_about_server_group_update(self._context,
                                                       "update", payload)

    @base.remotable
    def refresh(self):
        """Refreshes the instance group."""
        current = self.__class__.get_by_uuid(self._context, self.uuid)
        for field in self.fields:
            if self.obj_attr_is_set(field) and self[field] != current[field]:
                self[field] = current[field]
        self.obj_reset_changes()

    @base.remotable
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        updates = self.obj_get_changes()
        payload = dict(updates)
        updates.pop('id', None)
        policies = updates.pop('policies', None)
        members = updates.pop('members', None)

        db_inst = db.instance_group_create(self._context, updates,
                                           policies=policies,
                                           members=members)
        self._from_db_object(self._context, self, db_inst)
        payload['server_group_id'] = self.uuid
        compute_utils.notify_about_server_group_update(self._context,
                                                       "create", payload)

    @base.remotable
    def destroy(self):
        payload = {'server_group_id': self.uuid}
        db.instance_group_delete(self._context, self.uuid)
        self.obj_reset_changes()
        compute_utils.notify_about_server_group_update(self._context,
                                                       "delete", payload)

    @base.remotable_classmethod
    def add_members(cls, context, group_uuid, instance_uuids):
        payload = {'server_group_id': group_uuid,
                   'instance_uuids': instance_uuids}
        members = db.instance_group_members_add(context, group_uuid,
                instance_uuids)
        compute_utils.notify_about_server_group_update(context,
                                                       "addmember", payload)
        return list(members)

    @base.remotable
    def get_hosts(self, exclude=None):
        """Get a list of hosts for non-deleted instances in the group

        This method allows you to get a list of the hosts where instances in
        this group are currently running.  There's also an option to exclude
        certain instance UUIDs from this calculation.

        """
        filter_uuids = self.members
        if exclude:
            filter_uuids = set(filter_uuids) - set(exclude)
        filters = {'uuid': filter_uuids, 'deleted': False}
        instances = objects.InstanceList.get_by_filters(self._context,
                                                        filters=filters)
        return list(set([instance.host for instance in instances
                         if instance.host]))

    @base.remotable
    def count_members_by_user(self, user_id):
        """Count the number of instances in a group belonging to a user."""
        filter_uuids = self.members
        filters = {'uuid': filter_uuids, 'user_id': user_id, 'deleted': False}
        instances = objects.InstanceList.get_by_filters(self._context,
                                                        filters=filters)
        return len(instances)


@base.NovaObjectRegistry.register
class InstanceGroupList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    #              InstanceGroup <= version 1.3
    # Version 1.1: InstanceGroup <= version 1.4
    # Version 1.2: InstanceGroup <= version 1.5
    # Version 1.3: InstanceGroup <= version 1.6
    # Version 1.4: InstanceGroup <= version 1.7
    # Version 1.5: InstanceGroup <= version 1.8
    # Version 1.6: InstanceGroup <= version 1.9
    # Version 1.7: InstanceGroup <= version 1.10
    VERSION = '1.7'

    fields = {
        'objects': fields.ListOfObjectsField('InstanceGroup'),
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
