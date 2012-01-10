# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

from nova import local
from nova import utils


class RequestContext(object):
    """Security context and request information.

    Represents the user taking a given action within the system.

    """

    def __init__(self, user_id, project_id, is_admin=None, read_deleted="no",
                 roles=None, remote_address=None, timestamp=None,
                 request_id=None, auth_token=None, strategy='noauth',
                 overwrite=True):
        """
        :param read_deleted: 'no' indicates deleted records are hidden, 'yes'
            indicates deleted records are visible, 'only' indicates that
            *only* deleted records are visible.

        :param overwrite: Set to False to ensure that the greenthread local
            copy of the index is not overwritten.
        """
        self.user_id = user_id
        self.project_id = project_id
        self.roles = roles or []
        self.is_admin = is_admin
        if self.is_admin is None:
            self.is_admin = 'admin' in [x.lower() for x in self.roles]
        self.read_deleted = read_deleted
        self.remote_address = remote_address
        if not timestamp:
            timestamp = utils.utcnow()
        if isinstance(timestamp, basestring):
            timestamp = utils.parse_strtime(timestamp)
        self.timestamp = timestamp
        if not request_id:
            request_id = unicode(uuid.uuid4())
        self.request_id = request_id
        self.auth_token = auth_token
        self.strategy = strategy
        if overwrite or not hasattr(local.store, 'context'):
            local.store.context = self

    def to_dict(self):
        return {'user_id': self.user_id,
                'project_id': self.project_id,
                'is_admin': self.is_admin,
                'read_deleted': self.read_deleted,
                'roles': self.roles,
                'remote_address': self.remote_address,
                'timestamp': utils.strtime(self.timestamp),
                'request_id': self.request_id,
                'auth_token': self.auth_token,
                'strategy': self.strategy}

    @classmethod
    def from_dict(cls, values):
        return cls(**values)

    def elevated(self, read_deleted=None, overwrite=False):
        """Return a version of this context with admin flag set."""
        context = copy.copy(self)
        context.is_admin = True

        if read_deleted is not None:
            context.read_deleted = read_deleted

        return context


def get_admin_context(read_deleted="no"):
    return RequestContext(user_id=None,
                          project_id=None,
                          is_admin=True,
                          read_deleted=read_deleted,
                          overwrite=False)
