# Copyright 2011 OpenStack Foundation
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
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

"""RequestContext: context for requests that persist through all of nova."""

import copy
import uuid

import six

from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import local
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils
from nova import policy


LOG = logging.getLogger(__name__)


def generate_request_id():
    return 'req-' + str(uuid.uuid4())


class RequestContext(object):
    """Security context and request information.

    Represents the user taking a given action within the system.

    """

    def __init__(self, user_id, project_id, is_admin=None, read_deleted="no",
                 roles=None, remote_address=None, timestamp=None,
                 request_id=None, auth_token=None, overwrite=True,
                 quota_class=None, user_name=None, project_name=None,
                 service_catalog=None, instance_lock_checked=False, **kwargs):
        """:param read_deleted: 'no' indicates deleted records are hidden,
                'yes' indicates deleted records are visible,
                'only' indicates that *only* deleted records are visible.


           :param overwrite: Set to False to ensure that the greenthread local
                copy of the index is not overwritten.

           :param kwargs: Extra arguments that might be present, but we ignore
                because they possibly came in from older rpc messages.
        """
        if kwargs:
            LOG.warn(_('Arguments dropped when creating context: %s') %
                    str(kwargs))

        self.user_id = user_id
        self.project_id = project_id
        self.roles = roles or []
        self.read_deleted = read_deleted
        self.remote_address = remote_address
        if not timestamp:
            timestamp = timeutils.utcnow()
        if isinstance(timestamp, six.string_types):
            timestamp = timeutils.parse_strtime(timestamp)
        self.timestamp = timestamp
        if not request_id:
            request_id = generate_request_id()
        self.request_id = request_id
        self.auth_token = auth_token

        if service_catalog:
            # Only include required parts of service_catalog
            self.service_catalog = [s for s in service_catalog
                if s.get('type') in ('volume',)]
        else:
            # if list is empty or none
            self.service_catalog = []

        self.instance_lock_checked = instance_lock_checked

        # NOTE(markmc): this attribute is currently only used by the
        # rs_limits turnstile pre-processor.
        # See https://lists.launchpad.net/openstack/msg12200.html
        self.quota_class = quota_class
        self.user_name = user_name
        self.project_name = project_name
        self.is_admin = is_admin
        if self.is_admin is None:
            self.is_admin = policy.check_is_admin(self)
        if overwrite or not hasattr(local.store, 'context'):
            self.update_store()

    def _get_read_deleted(self):
        return self._read_deleted

    def _set_read_deleted(self, read_deleted):
        if read_deleted not in ('no', 'yes', 'only'):
            raise ValueError(_("read_deleted can only be one of 'no', "
                               "'yes' or 'only', not %r") % read_deleted)
        self._read_deleted = read_deleted

    def _del_read_deleted(self):
        del self._read_deleted

    read_deleted = property(_get_read_deleted, _set_read_deleted,
                            _del_read_deleted)

    def update_store(self):
        local.store.context = self

    def to_dict(self):
        return {'user_id': self.user_id,
                'project_id': self.project_id,
                'is_admin': self.is_admin,
                'read_deleted': self.read_deleted,
                'roles': self.roles,
                'remote_address': self.remote_address,
                'timestamp': timeutils.strtime(self.timestamp),
                'request_id': self.request_id,
                'auth_token': self.auth_token,
                'quota_class': self.quota_class,
                'user_name': self.user_name,
                'service_catalog': self.service_catalog,
                'project_name': self.project_name,
                'instance_lock_checked': self.instance_lock_checked,
                'tenant': self.tenant,
                'user': self.user}

    @classmethod
    def from_dict(cls, values):
        values.pop('user', None)
        values.pop('tenant', None)
        return cls(**values)

    def elevated(self, read_deleted=None, overwrite=False):
        """Return a version of this context with admin flag set."""
        context = copy.copy(self)
        context.is_admin = True

        if 'admin' not in context.roles:
            context.roles.append('admin')

        if read_deleted is not None:
            context.read_deleted = read_deleted

        return context

    # NOTE(sirp): the openstack/common version of RequestContext uses
    # tenant/user whereas the Nova version uses project_id/user_id. We need
    # this shim in order to use context-aware code from openstack/common, like
    # logging, until we make the switch to using openstack/common's version of
    # RequestContext.
    @property
    def tenant(self):
        return self.project_id

    @property
    def user(self):
        return self.user_id


def get_admin_context(read_deleted="no"):
    return RequestContext(user_id=None,
                          project_id=None,
                          is_admin=True,
                          read_deleted=read_deleted,
                          overwrite=False)


def is_user_context(context):
    """Indicates if the request context is a normal user."""
    if not context:
        return False
    if context.is_admin:
        return False
    if not context.user_id or not context.project_id:
        return False
    return True


def require_admin_context(ctxt):
    """Raise exception.AdminRequired() if context is an admin context."""
    if not ctxt.is_admin:
        raise exception.AdminRequired()


def require_context(ctxt):
    """Raise exception.NotAuthorized() if context is not a user or an
    admin context.
    """
    if not ctxt.is_admin and not is_user_context(ctxt):
        raise exception.NotAuthorized()


def authorize_project_context(context, project_id):
    """Ensures a request has permission to access the given project."""
    if is_user_context(context):
        if not context.project_id:
            raise exception.NotAuthorized()
        elif context.project_id != project_id:
            raise exception.NotAuthorized()


def authorize_user_context(context, user_id):
    """Ensures a request has permission to access the given user."""
    if is_user_context(context):
        if not context.user_id:
            raise exception.NotAuthorized()
        elif context.user_id != user_id:
            raise exception.NotAuthorized()


def authorize_quota_class_context(context, class_name):
    """Ensures a request has permission to access the given quota class."""
    if is_user_context(context):
        if not context.quota_class:
            raise exception.NotAuthorized()
        elif context.quota_class != class_name:
            raise exception.NotAuthorized()
