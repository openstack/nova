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

import copy

from oslo_db import exception as db_exc
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import uuidutils
from oslo_utils import versionutils
from sqlalchemy.orm import contains_eager
from sqlalchemy.orm import joinedload

from nova.compute import utils as compute_utils
from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import api_models
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields


LAZY_LOAD_FIELDS = ['hosts']
LOG = logging.getLogger(__name__)


def _instance_group_get_query(context, id_field=None, id=None):
    query = context.session.query(api_models.InstanceGroup).\
            options(joinedload('_policies')).\
            options(joinedload('_members'))
    if not context.is_admin:
        query = query.filter_by(project_id=context.project_id)
    if id and id_field:
        query = query.filter(id_field == id)
    return query


def _instance_group_model_get_query(context, model_class, group_id):
    return context.session.query(model_class).filter_by(group_id=group_id)


def _instance_group_model_add(context, model_class, items, item_models, field,
                              group_id, append_to_models=None):
    models = []
    already_existing = set()
    for db_item in item_models:
        already_existing.add(getattr(db_item, field))
        models.append(db_item)
    for item in items:
        if item in already_existing:
            continue
        model = model_class()
        values = {'group_id': group_id}
        values[field] = item
        model.update(values)
        context.session.add(model)
        if append_to_models:
            append_to_models.append(model)
        models.append(model)
    return models


def _instance_group_members_add(context, group, members):
    query = _instance_group_model_get_query(context,
                                            api_models.InstanceGroupMember,
                                            group.id)
    query = query.filter(
                api_models.InstanceGroupMember.instance_uuid.in_(set(members)))
    return _instance_group_model_add(context, api_models.InstanceGroupMember,
                                     members, query.all(), 'instance_uuid',
                                     group.id, append_to_models=group._members)


def _instance_group_members_add_by_uuid(context, group_uuid, members):
    # NOTE(melwitt): The condition on the join limits the number of members
    # returned to only those we wish to check as already existing.
    group = context.session.query(api_models.InstanceGroup).\
            outerjoin(api_models.InstanceGroupMember,
            api_models.InstanceGroupMember.instance_uuid.in_(set(members))).\
            filter(api_models.InstanceGroup.uuid == group_uuid).\
            options(contains_eager('_members')).first()
    if not group:
        raise exception.InstanceGroupNotFound(group_uuid=group_uuid)
    return _instance_group_model_add(context, api_models.InstanceGroupMember,
                                     members, group._members, 'instance_uuid',
                                     group.id)


# TODO(berrange): Remove NovaObjectDictCompat
# TODO(mriedem): Replace NovaPersistentObject with TimestampedObject in v2.0.
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
    # Version 1.11: Add policy and deprecate policies, add _rules
    VERSION = '1.11'

    fields = {
        'id': fields.IntegerField(),

        'user_id': fields.StringField(nullable=True),
        'project_id': fields.StringField(nullable=True),

        'uuid': fields.UUIDField(),
        'name': fields.StringField(nullable=True),

        'policies': fields.ListOfStringsField(nullable=True, read_only=True),
        'members': fields.ListOfStringsField(nullable=True),
        'hosts': fields.ListOfStringsField(nullable=True),
        'policy': fields.StringField(nullable=True),
        # NOTE(danms): Use rules not _rules for general access
        '_rules': fields.DictOfStringsField(),
        }

    def __init__(self, *args, **kwargs):
        if 'rules' in kwargs:
            kwargs['_rules'] = kwargs.pop('rules')
        super(InstanceGroup, self).__init__(*args, **kwargs)

    @property
    def rules(self):
        if '_rules' not in self:
            return {}
        # NOTE(danms): Coerce our rules into a typed dict for convenience
        rules = {}
        if 'max_server_per_host' in self._rules:
            rules['max_server_per_host'] = \
                    int(self._rules['max_server_per_host'])
        return rules

    def obj_make_compatible(self, primitive, target_version):
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 11):
            # NOTE(yikun): Before 1.11, we had a policies property which is
            # the list of policy name, even though it was a list, there was
            # ever only one entry in the list.
            policy = primitive.pop('policy', None)
            if policy:
                primitive['policies'] = [policy]
            else:
                primitive['policies'] = []
            primitive.pop('rules', None)
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
            # This is needed to handle db models from both the api
            # database and the main database. In the migration to
            # the api database, we have removed soft-delete, so
            # the object fields for delete must be filled in with
            # default values for db models from the api database.
            # TODO(mriedem): Remove this when NovaPersistentObject is removed.
            ignore = {'deleted': False,
                      'deleted_at': None}
            if '_rules' == field:
                db_policy = db_inst['policy']
                instance_group._rules = (
                    jsonutils.loads(db_policy['rules'])
                    if db_policy and db_policy['rules']
                    else {})
            elif field in ignore and not hasattr(db_inst, field):
                instance_group[field] = ignore[field]
            elif 'policies' == field:
                continue
            # NOTE(yikun): The obj.policies is deprecated and marked as
            # read_only in version 1.11, and there is no "policies" property
            # in InstanceGroup model anymore, so we just skip to set
            # "policies" and then load the "policies" when "policy" is set.
            elif 'policy' == field:
                db_policy = db_inst['policy']
                if db_policy:
                    instance_group.policy = db_policy['policy']
                    instance_group.policies = [instance_group.policy]
                else:
                    instance_group.policy = None
                    instance_group.policies = []
            else:
                instance_group[field] = db_inst[field]

        instance_group._context = context
        instance_group.obj_reset_changes()
        return instance_group

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_from_db_by_uuid(context, uuid):
        grp = _instance_group_get_query(context,
                                        id_field=api_models.InstanceGroup.uuid,
                                        id=uuid).first()
        if not grp:
            raise exception.InstanceGroupNotFound(group_uuid=uuid)
        return grp

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_from_db_by_id(context, id):
        grp = _instance_group_get_query(context,
                                        id_field=api_models.InstanceGroup.id,
                                        id=id).first()
        if not grp:
            raise exception.InstanceGroupNotFound(group_uuid=id)
        return grp

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_from_db_by_name(context, name):
        grp = _instance_group_get_query(context).filter_by(name=name).first()
        if not grp:
            raise exception.InstanceGroupNotFound(group_uuid=name)
        return grp

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_from_db_by_instance(context, instance_uuid):
        grp_member = context.session.query(api_models.InstanceGroupMember).\
                     filter_by(instance_uuid=instance_uuid).first()
        if not grp_member:
            raise exception.InstanceGroupNotFound(group_uuid='')
        grp = InstanceGroup._get_from_db_by_id(context, grp_member.group_id)
        return grp

    @staticmethod
    @db_api.api_context_manager.writer
    def _save_in_db(context, group_uuid, values):
        grp = InstanceGroup._get_from_db_by_uuid(context, group_uuid)
        values_copy = copy.copy(values)
        members = values_copy.pop('members', None)

        grp.update(values_copy)

        if members is not None:
            _instance_group_members_add(context, grp, members)

        return grp

    @staticmethod
    @db_api.api_context_manager.writer
    def _create_in_db(context, values, policies=None, members=None,
                      policy=None, rules=None):
        try:
            group = api_models.InstanceGroup()
            group.update(values)
            group.save(context.session)
        except db_exc.DBDuplicateEntry:
            raise exception.InstanceGroupIdExists(group_uuid=values['uuid'])

        if policies:
            db_policy = api_models.InstanceGroupPolicy(
                group_id=group['id'], policy=policies[0], rules=None)
            group._policies = [db_policy]
            group.rules = None
        elif policy:
            db_rules = jsonutils.dumps(rules or {})
            db_policy = api_models.InstanceGroupPolicy(
                group_id=group['id'], policy=policy,
                rules=db_rules)
            group._policies = [db_policy]
        else:
            group._policies = []

        if group._policies:
            group.save(context.session)

        if members:
            group._members = _instance_group_members_add(context, group,
                                                         members)
        else:
            group._members = []

        return group

    @staticmethod
    @db_api.api_context_manager.writer
    def _destroy_in_db(context, group_uuid):
        qry = _instance_group_get_query(context,
                                        id_field=api_models.InstanceGroup.uuid,
                                        id=group_uuid)
        if qry.count() == 0:
            raise exception.InstanceGroupNotFound(group_uuid=group_uuid)

        # Delete policies and members
        group_id = qry.first().id
        instance_models = [api_models.InstanceGroupPolicy,
                           api_models.InstanceGroupMember]
        for model in instance_models:
            context.session.query(model).filter_by(group_id=group_id).delete()

        qry.delete()

    @staticmethod
    @db_api.api_context_manager.writer
    def _add_members_in_db(context, group_uuid, members):
        return _instance_group_members_add_by_uuid(context, group_uuid,
                                                   members)

    @staticmethod
    @db_api.api_context_manager.writer
    def _remove_members_in_db(context, group_id, instance_uuids):
        # There is no public method provided for removing members because the
        # user-facing API doesn't allow removal of instance group members. We
        # need to be able to remove members to address quota races.
        context.session.query(api_models.InstanceGroupMember).\
            filter_by(group_id=group_id).\
            filter(api_models.InstanceGroupMember.instance_uuid.
                   in_(set(instance_uuids))).\
            delete(synchronize_session=False)

    @staticmethod
    @db_api.api_context_manager.writer
    def _destroy_members_bulk_in_db(context, instance_uuids):
        return context.session.query(api_models.InstanceGroupMember).filter(
            api_models.InstanceGroupMember.instance_uuid.in_(instance_uuids)).\
            delete(synchronize_session=False)

    @classmethod
    def destroy_members_bulk(cls, context, instance_uuids):
        return cls._destroy_members_bulk_in_db(context, instance_uuids)

    def obj_load_attr(self, attrname):
        # NOTE(sbauza): Only hosts could be lazy-loaded right now
        if attrname != 'hosts':
            raise exception.ObjectActionError(
                action='obj_load_attr', reason='unable to load %s' % attrname)

        LOG.debug("Lazy-loading '%(attr)s' on %(name)s uuid %(uuid)s",
                  {'attr': attrname,
                   'name': self.obj_name(),
                   'uuid': self.uuid,
                   })

        self.hosts = self.get_hosts()
        self.obj_reset_changes(['hosts'])

    @base.remotable_classmethod
    def get_by_uuid(cls, context, uuid):
        db_group = cls._get_from_db_by_uuid(context, uuid)
        return cls._from_db_object(context, cls(), db_group)

    @base.remotable_classmethod
    def get_by_name(cls, context, name):
        db_group = cls._get_from_db_by_name(context, name)
        return cls._from_db_object(context, cls(), db_group)

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        db_group = cls._get_from_db_by_instance(context, instance_uuid)
        return cls._from_db_object(context, cls(), db_group)

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

        # NOTE(yikun): You have to provide exactly one policy on group create,
        # and also there are no group update APIs, so we do NOT support
        # policies update.
        if 'policies' in updates:
            raise exception.InstanceGroupSaveException(field='policies')

        if not updates:
            return

        payload = dict(updates)
        payload['server_group_id'] = self.uuid

        db_group = self._save_in_db(self._context, self.uuid, updates)
        self._from_db_object(self._context, self, db_group)
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
        policy = updates.pop('policy', None)
        rules = updates.pop('_rules', None)
        members = updates.pop('members', None)

        if 'uuid' not in updates:
            self.uuid = uuidutils.generate_uuid()
            updates['uuid'] = self.uuid

        db_group = self._create_in_db(self._context, updates,
                                      policies=policies,
                                      members=members,
                                      policy=policy,
                                      rules=rules)
        self._from_db_object(self._context, self, db_group)
        payload['server_group_id'] = self.uuid
        compute_utils.notify_about_server_group_update(self._context,
                                                       "create", payload)
        compute_utils.notify_about_server_group_action(
            context=self._context,
            group=self,
            action=fields.NotificationAction.CREATE)

    @base.remotable
    def destroy(self):
        payload = {'server_group_id': self.uuid}
        self._destroy_in_db(self._context, self.uuid)
        self.obj_reset_changes()
        compute_utils.notify_about_server_group_update(self._context,
                                                       "delete", payload)
        compute_utils.notify_about_server_group_action(
            context=self._context,
            group=self,
            action=fields.NotificationAction.DELETE)

    @base.remotable_classmethod
    def add_members(cls, context, group_uuid, instance_uuids):
        payload = {'server_group_id': group_uuid,
                   'instance_uuids': instance_uuids}
        members = cls._add_members_in_db(context, group_uuid,
                                         instance_uuids)
        members = [member['instance_uuid'] for member in members]
        compute_utils.notify_about_server_group_update(context,
                                                       "addmember", payload)
        compute_utils.notify_about_server_group_add_member(context, group_uuid)
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
        # Pass expected_attrs=[] to avoid unnecessary joins.
        # TODO(mriedem): This is pretty inefficient since all we care about
        # are the hosts. We could optimize this with a single-purpose SQL query
        # like:
        #   SELECT host FROM instances WHERE deleted=0 AND host IS NOT NULL
        #       AND uuid IN ($filter_uuids) GROUP BY host;
        instances = objects.InstanceList.get_by_filters(self._context,
                                                        filters=filters,
                                                        expected_attrs=[])
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
    # Version 1.8: Added get_counts() for quotas
    VERSION = '1.8'

    fields = {
        'objects': fields.ListOfObjectsField('InstanceGroup'),
        }

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_from_db(context, project_id=None):
        query = _instance_group_get_query(context)
        if project_id is not None:
            query = query.filter_by(project_id=project_id)
        return query.all()

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_counts_from_db(context, project_id, user_id=None):
        query = context.session.query(api_models.InstanceGroup.id).\
                filter_by(project_id=project_id)
        counts = {}
        counts['project'] = {'server_groups': query.count()}
        if user_id:
            query = query.filter_by(user_id=user_id)
            counts['user'] = {'server_groups': query.count()}
        return counts

    @base.remotable_classmethod
    def get_by_project_id(cls, context, project_id):
        api_db_groups = cls._get_from_db(context, project_id=project_id)
        return base.obj_make_list(context, cls(context), objects.InstanceGroup,
                                  api_db_groups)

    @base.remotable_classmethod
    def get_all(cls, context):
        api_db_groups = cls._get_from_db(context)
        return base.obj_make_list(context, cls(context), objects.InstanceGroup,
                                  api_db_groups)

    @base.remotable_classmethod
    def get_counts(cls, context, project_id, user_id=None):
        """Get the counts of InstanceGroup objects in the database.

        :param context: The request context for database access
        :param project_id: The project_id to count across
        :param user_id: The user_id to count across
        :returns: A dict containing the project-scoped counts and user-scoped
                  counts if user_id is specified. For example:

                    {'project': {'server_groups': <count across project>},
                     'user': {'server_groups': <count across user>}}
        """
        return cls._get_counts_from_db(context, project_id, user_id=user_id)
