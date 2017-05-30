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

from nova import db
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

    @classmethod
    def from_reservations(cls, context, reservations, instance=None):
        """Transitional for compatibility."""
        if instance is None:
            project_id = None
            user_id = None
        else:
            project_id, user_id = ids_from_instance(context, instance)
        quotas = cls()
        quotas._context = context
        quotas.reservations = reservations
        quotas.project_id = project_id
        quotas.user_id = user_id
        quotas.obj_reset_changes()
        return quotas

    @base.remotable
    def reserve(self, expire=None, project_id=None, user_id=None,
                **deltas):
        reservations = quota.QUOTAS.reserve(self._context, expire=expire,
                                            project_id=project_id,
                                            user_id=user_id,
                                            **deltas)
        self.reservations = reservations
        self.project_id = project_id
        self.user_id = user_id
        self.obj_reset_changes()

    @base.remotable
    def commit(self):
        if not self.reservations:
            return
        quota.QUOTAS.commit(self._context, self.reservations,
                            project_id=self.project_id,
                            user_id=self.user_id)
        self.reservations = None
        self.obj_reset_changes()

    @base.remotable
    def rollback(self):
        """Rollback quotas."""
        if not self.reservations:
            return
        quota.QUOTAS.rollback(self._context, self.reservations,
                              project_id=self.project_id,
                              user_id=self.user_id)
        self.reservations = None
        self.obj_reset_changes()

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
        # NOTE(danms,comstud): Quotas likely needs an overhaul and currently
        # doesn't map very well to objects. Since there is quite a bit of
        # logic in the db api layer for this, just pass this through for now.
        db.quota_create(context, project_id, resource, limit, user_id=user_id)

    @base.remotable_classmethod
    def update_limit(cls, context, project_id, resource, limit, user_id=None):
        # NOTE(danms,comstud): Quotas likely needs an overhaul and currently
        # doesn't map very well to objects. Since there is quite a bit of
        # logic in the db api layer for this, just pass this through for now.
        db.quota_update(context, project_id, resource, limit, user_id=user_id)


@base.NovaObjectRegistry.register
class QuotasNoOp(Quotas):
    def reserve(context, expire=None, project_id=None, user_id=None,
                **deltas):
        pass

    def commit(self, context=None):
        pass

    def rollback(self, context=None):
        pass
