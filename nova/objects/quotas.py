#    Copyright 2013 Rackspace Hosting.
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

import collections

from oslo_db import exception as db_exc

from nova import db
from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import api_models
from nova.db.sqlalchemy import models as main_models
from nova import exception
from nova.objects import base
from nova.objects import fields
from nova import quota


def ids_from_instance(context, instance):
    if (context.is_admin and
            context.project_id != instance['project_id']):
        project_id = instance['project_id']
    else:
        project_id = context.project_id
    if context.user_id != instance['user_id']:
        user_id = instance['user_id']
    else:
        user_id = context.user_id
    return project_id, user_id


# TODO(lyj): This method needs to be cleaned up once the
# ids_from_instance helper method is renamed or some common
# method is added for objects.quotas.
def ids_from_security_group(context, security_group):
    return ids_from_instance(context, security_group)


# TODO(PhilD): This method needs to be cleaned up once the
# ids_from_instance helper method is renamed or some common
# method is added for objects.quotas.
def ids_from_server_group(context, server_group):
    return ids_from_instance(context, server_group)


@base.NovaObjectRegistry.register
class Quotas(base.NovaObject):
    # Version 1.0: initial version
    # Version 1.1: Added create_limit() and update_limit()
    # Version 1.2: Added limit_check() and count()
    # Version 1.3: Added check_deltas(), limit_check_project_and_user(),
    #              and count_as_dict()
    VERSION = '1.3'

    fields = {
        # TODO(melwitt): Remove this field in version 2.0 of the object.
        'reservations': fields.ListOfStringsField(nullable=True),
        'project_id': fields.StringField(nullable=True),
        'user_id': fields.StringField(nullable=True),
    }

    def __init__(self, *args, **kwargs):
        super(Quotas, self).__init__(*args, **kwargs)
        # Set up defaults.
        self.reservations = []
        self.project_id = None
        self.user_id = None
        self.obj_reset_changes()

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_from_db(context, project_id, resource, user_id=None):
        model = api_models.ProjectUserQuota if user_id else api_models.Quota
        query = context.session.query(model).\
                        filter_by(project_id=project_id).\
                        filter_by(resource=resource)
        if user_id:
            query = query.filter_by(user_id=user_id)
        result = query.first()
        if not result:
            if user_id:
                raise exception.ProjectUserQuotaNotFound(project_id=project_id,
                                                         user_id=user_id)
            else:
                raise exception.ProjectQuotaNotFound(project_id=project_id)
        return result

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_all_from_db(context, project_id):
        return context.session.query(api_models.ProjectUserQuota).\
                        filter_by(project_id=project_id).\
                        all()

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_all_from_db_by_project(context, project_id):
        # by_project refers to the returned dict that has a 'project_id' key
        rows = context.session.query(api_models.Quota).\
                        filter_by(project_id=project_id).\
                        all()
        result = {'project_id': project_id}
        for row in rows:
            result[row.resource] = row.hard_limit
        return result

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_all_from_db_by_project_and_user(context, project_id, user_id):
        # by_project_and_user refers to the returned dict that has
        # 'project_id' and 'user_id' keys
        columns = (api_models.ProjectUserQuota.resource,
                   api_models.ProjectUserQuota.hard_limit)
        user_quotas = context.session.query(*columns).\
                        filter_by(project_id=project_id).\
                        filter_by(user_id=user_id).\
                        all()
        result = {'project_id': project_id, 'user_id': user_id}
        for user_quota in user_quotas:
            result[user_quota.resource] = user_quota.hard_limit
        return result

    @staticmethod
    @db_api.api_context_manager.writer
    def _destroy_all_in_db_by_project(context, project_id):
        per_project = context.session.query(api_models.Quota).\
                            filter_by(project_id=project_id).\
                            delete(synchronize_session=False)
        per_user = context.session.query(api_models.ProjectUserQuota).\
                            filter_by(project_id=project_id).\
                            delete(synchronize_session=False)
        if not per_project and not per_user:
            raise exception.ProjectQuotaNotFound(project_id=project_id)

    @staticmethod
    @db_api.api_context_manager.writer
    def _destroy_all_in_db_by_project_and_user(context, project_id, user_id):
        result = context.session.query(api_models.ProjectUserQuota).\
                        filter_by(project_id=project_id).\
                        filter_by(user_id=user_id).\
                        delete(synchronize_session=False)
        if not result:
            raise exception.ProjectUserQuotaNotFound(project_id=project_id,
                                                     user_id=user_id)

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_class_from_db(context, class_name, resource):
        result = context.session.query(api_models.QuotaClass).\
                        filter_by(class_name=class_name).\
                        filter_by(resource=resource).\
                        first()
        if not result:
            raise exception.QuotaClassNotFound(class_name=class_name)
        return result

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_all_class_from_db_by_name(context, class_name):
        # by_name refers to the returned dict that has a 'class_name' key
        rows = context.session.query(api_models.QuotaClass).\
                        filter_by(class_name=class_name).\
                        all()
        result = {'class_name': class_name}
        for row in rows:
            result[row.resource] = row.hard_limit
        return result

    @staticmethod
    @db_api.api_context_manager.writer
    def _create_limit_in_db(context, project_id, resource, limit,
                            user_id=None):
        # TODO(melwitt): We won't have per project resources after nova-network
        # is removed.
        per_user = (user_id and
                    resource not in db_api.quota_get_per_project_resources())
        quota_ref = (api_models.ProjectUserQuota() if per_user
                     else api_models.Quota())
        if per_user:
            quota_ref.user_id = user_id
        quota_ref.project_id = project_id
        quota_ref.resource = resource
        quota_ref.hard_limit = limit
        try:
            quota_ref.save(context.session)
        except db_exc.DBDuplicateEntry:
            raise exception.QuotaExists(project_id=project_id,
                                        resource=resource)
        return quota_ref

    @staticmethod
    @db_api.api_context_manager.writer
    def _update_limit_in_db(context, project_id, resource, limit,
                            user_id=None):
        # TODO(melwitt): We won't have per project resources after nova-network
        # is removed.
        per_user = (user_id and
                    resource not in db_api.quota_get_per_project_resources())
        model = api_models.ProjectUserQuota if per_user else api_models.Quota
        query = context.session.query(model).\
                        filter_by(project_id=project_id).\
                        filter_by(resource=resource)
        if per_user:
            query = query.filter_by(user_id=user_id)

        result = query.update({'hard_limit': limit})
        if not result:
            if per_user:
                raise exception.ProjectUserQuotaNotFound(project_id=project_id,
                                                         user_id=user_id)
            else:
                raise exception.ProjectQuotaNotFound(project_id=project_id)

    @staticmethod
    @db_api.api_context_manager.writer
    def _create_class_in_db(context, class_name, resource, limit):
        # NOTE(melwitt): There's no unique constraint on the QuotaClass model,
        # so check for duplicate manually.
        try:
            Quotas._get_class_from_db(context, class_name, resource)
        except exception.QuotaClassNotFound:
            pass
        else:
            raise exception.QuotaClassExists(class_name=class_name,
                                             resource=resource)
        quota_class_ref = api_models.QuotaClass()
        quota_class_ref.class_name = class_name
        quota_class_ref.resource = resource
        quota_class_ref.hard_limit = limit
        quota_class_ref.save(context.session)
        return quota_class_ref

    @staticmethod
    @db_api.api_context_manager.writer
    def _update_class_in_db(context, class_name, resource, limit):
        result = context.session.query(api_models.QuotaClass).\
                        filter_by(class_name=class_name).\
                        filter_by(resource=resource).\
                        update({'hard_limit': limit})
        if not result:
            raise exception.QuotaClassNotFound(class_name=class_name)

    # TODO(melwitt): Remove this method in version 2.0 of the object.
    @base.remotable
    def reserve(self, expire=None, project_id=None, user_id=None,
                **deltas):
        # Honor the expected attributes even though we're not reserving
        # anything anymore. This will protect against things exploding if
        # someone has an Ocata compute host running by accident, for example.
        self.reservations = None
        self.project_id = project_id
        self.user_id = user_id
        self.obj_reset_changes()

    # TODO(melwitt): Remove this method in version 2.0 of the object.
    @base.remotable
    def commit(self):
        pass

    # TODO(melwitt): Remove this method in version 2.0 of the object.
    @base.remotable
    def rollback(self):
        pass

    @base.remotable_classmethod
    def limit_check(cls, context, project_id=None, user_id=None, **values):
        """Check quota limits."""
        return quota.QUOTAS.limit_check(
            context, project_id=project_id, user_id=user_id, **values)

    @base.remotable_classmethod
    def limit_check_project_and_user(cls, context, project_values=None,
                                     user_values=None, project_id=None,
                                     user_id=None):
        """Check values against quota limits."""
        return quota.QUOTAS.limit_check_project_and_user(context,
            project_values=project_values, user_values=user_values,
            project_id=project_id, user_id=user_id)

    # NOTE(melwitt): This can be removed once no old code can call count().
    @base.remotable_classmethod
    def count(cls, context, resource, *args, **kwargs):
        """Count a resource."""
        count = quota.QUOTAS.count_as_dict(context, resource, *args, **kwargs)
        key = 'user' if 'user' in count else 'project'
        return count[key][resource]

    @base.remotable_classmethod
    def count_as_dict(cls, context, resource, *args, **kwargs):
        """Count a resource and return a dict."""
        return quota.QUOTAS.count_as_dict(
            context, resource, *args, **kwargs)

    @base.remotable_classmethod
    def check_deltas(cls, context, deltas, *count_args, **count_kwargs):
        """Check usage delta against quota limits.

        This does a Quotas.count_as_dict() followed by a
        Quotas.limit_check_project_and_user() using the provided deltas.

        :param context: The request context, for access checks
        :param deltas: A dict of {resource_name: delta, ...} to check against
                       the quota limits
        :param count_args: Optional positional arguments to pass to
                           count_as_dict()
        :param count_kwargs: Optional keyword arguments to pass to
                             count_as_dict()
        :param check_project_id: Optional project_id for scoping the limit
                                 check to a different project than in the
                                 context
        :param check_user_id: Optional user_id for scoping the limit check to a
                              different user than in the context
        :raises: exception.OverQuota if the limit check exceeds the quota
                 limits
        """
        # We can't do f(*args, kw=None, **kwargs) in python 2.x
        check_project_id = count_kwargs.pop('check_project_id', None)
        check_user_id = count_kwargs.pop('check_user_id', None)

        check_kwargs = collections.defaultdict(dict)
        for resource in deltas:
            # If we already counted a resource in a batch count, avoid
            # unnecessary re-counting and avoid creating empty dicts in
            # the defaultdict.
            if (resource in check_kwargs.get('project_values', {}) or
                    resource in check_kwargs.get('user_values', {})):
                continue
            count = cls.count_as_dict(context, resource, *count_args,
                                      **count_kwargs)
            for res in count.get('project', {}):
                if res in deltas:
                    total = count['project'][res] + deltas[res]
                    check_kwargs['project_values'][res] = total
            for res in count.get('user', {}):
                if res in deltas:
                    total = count['user'][res] + deltas[res]
                    check_kwargs['user_values'][res] = total
        if check_project_id is not None:
            check_kwargs['project_id'] = check_project_id
        if check_user_id is not None:
            check_kwargs['user_id'] = check_user_id
        try:
            cls.limit_check_project_and_user(context, **check_kwargs)
        except exception.OverQuota as exc:
            # Report usage in the exception when going over quota
            key = 'user' if 'user' in count else 'project'
            exc.kwargs['usages'] = count[key]
            raise exc

    @base.remotable_classmethod
    def create_limit(cls, context, project_id, resource, limit, user_id=None):
        try:
            db.quota_get(context, project_id, resource, user_id=user_id)
        except exception.QuotaNotFound:
            cls._create_limit_in_db(context, project_id, resource, limit,
                                    user_id=user_id)
        else:
            raise exception.QuotaExists(project_id=project_id,
                                        resource=resource)

    @base.remotable_classmethod
    def update_limit(cls, context, project_id, resource, limit, user_id=None):
        try:
            cls._update_limit_in_db(context, project_id, resource, limit,
                                    user_id=user_id)
        except exception.QuotaNotFound:
            db.quota_update(context, project_id, resource, limit,
                            user_id=user_id)

    @classmethod
    def create_class(cls, context, class_name, resource, limit):
        try:
            db.quota_class_get(context, class_name, resource)
        except exception.QuotaClassNotFound:
            cls._create_class_in_db(context, class_name, resource, limit)
        else:
            raise exception.QuotaClassExists(class_name=class_name,
                                             resource=resource)

    @classmethod
    def update_class(cls, context, class_name, resource, limit):
        try:
            cls._update_class_in_db(context, class_name, resource, limit)
        except exception.QuotaClassNotFound:
            db.quota_class_update(context, class_name, resource, limit)

    # NOTE(melwitt): The following methods are not remotable and return
    # dict-like database model objects. We are using classmethods to provide
    # a common interface for accessing the api/main databases.
    @classmethod
    def get(cls, context, project_id, resource, user_id=None):
        try:
            quota = cls._get_from_db(context, project_id, resource,
                                     user_id=user_id)
        except exception.QuotaNotFound:
            quota = db.quota_get(context, project_id, resource,
                                 user_id=user_id)
        return quota

    @classmethod
    def get_all(cls, context, project_id):
        api_db_quotas = cls._get_all_from_db(context, project_id)
        main_db_quotas = db.quota_get_all(context, project_id)
        return api_db_quotas + main_db_quotas

    @classmethod
    def get_all_by_project(cls, context, project_id):
        api_db_quotas_dict = cls._get_all_from_db_by_project(context,
                                                             project_id)
        main_db_quotas_dict = db.quota_get_all_by_project(context, project_id)
        for k, v in api_db_quotas_dict.items():
            main_db_quotas_dict[k] = v
        return main_db_quotas_dict

    @classmethod
    def get_all_by_project_and_user(cls, context, project_id, user_id):
        api_db_quotas_dict = cls._get_all_from_db_by_project_and_user(
                context, project_id, user_id)
        main_db_quotas_dict = db.quota_get_all_by_project_and_user(
                context, project_id, user_id)
        for k, v in api_db_quotas_dict.items():
            main_db_quotas_dict[k] = v
        return main_db_quotas_dict

    @classmethod
    def destroy_all_by_project(cls, context, project_id):
        try:
            cls._destroy_all_in_db_by_project(context, project_id)
        except exception.ProjectQuotaNotFound:
            db.quota_destroy_all_by_project(context, project_id)

    @classmethod
    def destroy_all_by_project_and_user(cls, context, project_id, user_id):
        try:
            cls._destroy_all_in_db_by_project_and_user(context, project_id,
                                                       user_id)
        except exception.ProjectUserQuotaNotFound:
            db.quota_destroy_all_by_project_and_user(context, project_id,
                                                     user_id)

    @classmethod
    def get_class(cls, context, class_name, resource):
        try:
            qclass = cls._get_class_from_db(context, class_name, resource)
        except exception.QuotaClassNotFound:
            qclass = db.quota_class_get(context, class_name, resource)
        return qclass

    @classmethod
    def get_default_class(cls, context):
        try:
            qclass = cls._get_all_class_from_db_by_name(
                    context, db_api._DEFAULT_QUOTA_NAME)
        except exception.QuotaClassNotFound:
            qclass = db.quota_class_get_default(context)
        return qclass

    @classmethod
    def get_all_class_by_name(cls, context, class_name):
        api_db_quotas_dict = cls._get_all_class_from_db_by_name(context,
                                                                class_name)
        main_db_quotas_dict = db.quota_class_get_all_by_name(context,
                                                             class_name)
        for k, v in api_db_quotas_dict.items():
            main_db_quotas_dict[k] = v
        return main_db_quotas_dict


@base.NovaObjectRegistry.register
class QuotasNoOp(Quotas):
    # TODO(melwitt): Remove this method in version 2.0 of the object.
    def reserve(context, expire=None, project_id=None, user_id=None,
                **deltas):
        pass

    # TODO(melwitt): Remove this method in version 2.0 of the object.
    def commit(self, context=None):
        pass

    # TODO(melwitt): Remove this method in version 2.0 of the object.
    def rollback(self, context=None):
        pass

    def check_deltas(cls, context, deltas, *count_args, **count_kwargs):
        pass


@db_api.require_context
@db_api.pick_context_manager_reader
def _get_main_per_project_limits(context, limit):
    return context.session.query(main_models.Quota).\
        filter_by(deleted=0).\
        limit(limit).\
        all()


@db_api.require_context
@db_api.pick_context_manager_reader
def _get_main_per_user_limits(context, limit):
    return context.session.query(main_models.ProjectUserQuota).\
        filter_by(deleted=0).\
        limit(limit).\
        all()


@db_api.require_context
@db_api.pick_context_manager_writer
def _destroy_main_per_project_limits(context, project_id, resource):
    context.session.query(main_models.Quota).\
        filter_by(deleted=0).\
        filter_by(project_id=project_id).\
        filter_by(resource=resource).\
        soft_delete(synchronize_session=False)


@db_api.require_context
@db_api.pick_context_manager_writer
def _destroy_main_per_user_limits(context, project_id, resource, user_id):
    context.session.query(main_models.ProjectUserQuota).\
        filter_by(deleted=0).\
        filter_by(project_id=project_id).\
        filter_by(user_id=user_id).\
        filter_by(resource=resource).\
        soft_delete(synchronize_session=False)


@db_api.api_context_manager.writer
def _create_limits_in_api_db(context, db_limits, per_user=False):
    for db_limit in db_limits:
        user_id = db_limit.user_id if per_user else None
        Quotas._create_limit_in_db(context, db_limit.project_id,
                                   db_limit.resource, db_limit.hard_limit,
                                   user_id=user_id)


def migrate_quota_limits_to_api_db(context, count):
    # Migrate per project limits
    main_per_project_limits = _get_main_per_project_limits(context, count)
    done = 0
    try:
        # Create all the limits in a single transaction.
        _create_limits_in_api_db(context, main_per_project_limits)
    except exception.QuotaExists:
        # NOTE(melwitt): This can happen if the migration is interrupted after
        # limits were created in the api db but before they were deleted from
        # the main db, and the migration is re-run.
        pass
    # Delete the limits separately.
    for db_limit in main_per_project_limits:
        _destroy_main_per_project_limits(context, db_limit.project_id,
                                         db_limit.resource)
        done += 1
    if done == count:
        return len(main_per_project_limits), done
    # Migrate per user limits
    count -= done
    main_per_user_limits = _get_main_per_user_limits(context, count)
    try:
        # Create all the limits in a single transaction.
        _create_limits_in_api_db(context, main_per_user_limits, per_user=True)
    except exception.QuotaExists:
        # NOTE(melwitt): This can happen if the migration is interrupted after
        # limits were created in the api db but before they were deleted from
        # the main db, and the migration is re-run.
        pass
    # Delete the limits separately.
    for db_limit in main_per_user_limits:
        _destroy_main_per_user_limits(context, db_limit.project_id,
                                      db_limit.resource, db_limit.user_id)
        done += 1
    return len(main_per_project_limits) + len(main_per_user_limits), done


@db_api.require_context
@db_api.pick_context_manager_reader
def _get_main_quota_classes(context, limit):
    return context.session.query(main_models.QuotaClass).\
        filter_by(deleted=0).\
        limit(limit).\
        all()


@db_api.pick_context_manager_writer
def _destroy_main_quota_classes(context, db_classes):
    for db_class in db_classes:
        context.session.query(main_models.QuotaClass).\
            filter_by(deleted=0).\
            filter_by(id=db_class.id).\
            soft_delete(synchronize_session=False)


@db_api.api_context_manager.writer
def _create_classes_in_api_db(context, db_classes):
    for db_class in db_classes:
        Quotas._create_class_in_db(context, db_class.class_name,
                                   db_class.resource, db_class.hard_limit)


def migrate_quota_classes_to_api_db(context, count):
    main_quota_classes = _get_main_quota_classes(context, count)
    done = 0
    try:
        # Create all the classes in a single transaction.
        _create_classes_in_api_db(context, main_quota_classes)
    except exception.QuotaClassExists:
        # NOTE(melwitt): This can happen if the migration is interrupted after
        # classes were created in the api db but before they were deleted from
        # the main db, and the migration is re-run.
        pass
    # Delete the classes in a single transaction.
    _destroy_main_quota_classes(context, main_quota_classes)
    found = done = len(main_quota_classes)
    return found, done
