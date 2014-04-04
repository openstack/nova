# Copyright 2011 OpenStack Foundation.
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

"""
Simple class that stores security context information in the web request.

Projects should subclass this class if they wish to enhance the request
context or provide additional information in their specific WSGI pipeline.
"""

import itertools
import uuid


def generate_request_id():
    return 'req-%s' % str(uuid.uuid4())


class RequestContext(object):

    """Helper class to represent useful information about a request context.

    Stores information about the security context under which the user
    accesses the system, as well as additional request information.
    """

    user_idt_format = '{user} {tenant} {domain} {user_domain} {p_domain}'

    def __init__(self, auth_token=None, user=None, tenant=None, domain=None,
                 user_domain=None, project_domain=None, is_admin=False,
                 read_only=False, show_deleted=False, request_id=None,
                 instance_uuid=None):
        self.auth_token = auth_token
        self.user = user
        self.tenant = tenant
        self.domain = domain
        self.user_domain = user_domain
        self.project_domain = project_domain
        self.is_admin = is_admin
        self.read_only = read_only
        self.show_deleted = show_deleted
        self.instance_uuid = instance_uuid
        if not request_id:
            request_id = generate_request_id()
        self.request_id = request_id

    def to_dict(self):
        user_idt = (
            self.user_idt_format.format(user=self.user or '-',
                                        tenant=self.tenant or '-',
                                        domain=self.domain or '-',
                                        user_domain=self.user_domain or '-',
                                        p_domain=self.project_domain or '-'))

        return {'user': self.user,
                'tenant': self.tenant,
                'domain': self.domain,
                'user_domain': self.user_domain,
                'project_domain': self.project_domain,
                'is_admin': self.is_admin,
                'read_only': self.read_only,
                'show_deleted': self.show_deleted,
                'auth_token': self.auth_token,
                'request_id': self.request_id,
                'instance_uuid': self.instance_uuid,
                'user_identity': user_idt}


def get_admin_context(show_deleted=False):
    context = RequestContext(None,
                             tenant=None,
                             is_admin=True,
                             show_deleted=show_deleted)
    return context


def get_context_from_function_and_args(function, args, kwargs):
    """Find an arg of type RequestContext and return it.

       This is useful in a couple of decorators where we don't
       know much about the function we're wrapping.
    """

    for arg in itertools.chain(kwargs.values(), args):
        if isinstance(arg, RequestContext):
            return arg

    return None


def is_user_context(context):
    """Indicates if the request context is a normal user."""
    if not context:
        return False
    if context.is_admin:
        return False
    if not context.user_id or not context.project_id:
        return False
    return True
