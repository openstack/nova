# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import datetime
import random

from nova import exception
from nova import utils


class RequestContext(object):
    """Security context and request information.

    Represents the user taking a given action within the system.

    """

    def __init__(self, user, project, is_admin=None, read_deleted=False,
                 remote_address=None, timestamp=None, request_id=None):
        if hasattr(user, 'id'):
            self._user = user
            self.user_id = user.id
        else:
            self._user = None
            self.user_id = user
        if hasattr(project, 'id'):
            self._project = project
            self.project_id = project.id
        else:
            self._project = None
            self.project_id = project
        if is_admin is None:
            if self.user_id and self.user:
                self.is_admin = self.user.is_admin()
            else:
                self.is_admin = False
        else:
            self.is_admin = is_admin
        self.read_deleted = read_deleted
        self.remote_address = remote_address
        if not timestamp:
            timestamp = utils.utcnow()
        if isinstance(timestamp, str) or isinstance(timestamp, unicode):
            timestamp = utils.parse_isotime(timestamp)
        self.timestamp = timestamp
        if not request_id:
            chars = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ1234567890-'
            request_id = ''.join([random.choice(chars) for x in xrange(20)])
        self.request_id = request_id

    @property
    def user(self):
        # NOTE(vish): Delay import of manager, so that we can import this
        #             file from manager.
        from nova.auth import manager
        if not self._user:
            try:
                self._user = manager.AuthManager().get_user(self.user_id)
            except exception.NotFound:
                pass
        return self._user

    @property
    def project(self):
        # NOTE(vish): Delay import of manager, so that we can import this
        #             file from manager.
        from nova.auth import manager
        if not self._project:
            try:
                auth_manager = manager.AuthManager()
                self._project = auth_manager.get_project(self.project_id)
            except exception.NotFound:
                pass
        return self._project

    def to_dict(self):
        return {'user': self.user_id,
                'project': self.project_id,
                'is_admin': self.is_admin,
                'read_deleted': self.read_deleted,
                'remote_address': self.remote_address,
                'timestamp': utils.isotime(self.timestamp),
                'request_id': self.request_id}

    @classmethod
    def from_dict(cls, values):
        return cls(**values)

    def elevated(self, read_deleted=False):
        """Return a version of this context with admin flag set."""
        return RequestContext(self.user_id,
                              self.project_id,
                              True,
                              read_deleted,
                              self.remote_address,
                              self.timestamp,
                              self.request_id)


def get_admin_context(read_deleted=False):
    return RequestContext(None, None, True, read_deleted)
