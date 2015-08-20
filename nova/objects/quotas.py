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


from nova import db
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
    VERSION = '1.2'

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
    def count(cls, context, resource, *args, **kwargs):
        """Count a resource."""
        return quota.QUOTAS.count(
            context, resource, *args, **kwargs)

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
