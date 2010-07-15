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

from nova import exception
from nova.auth import users


def allow(*roles):
    def wrap(f):
        def wrapped_f(self, context, *args, **kwargs):
            if context.user.is_superuser():
                return f(self, context, *args, **kwargs)
            for role in roles:
                if __matches_role(context, role):
                    return f(self, context, *args, **kwargs)
            raise exception.NotAuthorized()
        return wrapped_f
    return wrap

def deny(*roles):
    def wrap(f):
        def wrapped_f(self, context, *args, **kwargs):
            if context.user.is_superuser():
                return f(self, context, *args, **kwargs)
            for role in roles:
                if __matches_role(context, role):
                    raise exception.NotAuthorized()
            return f(self, context, *args, **kwargs)
        return wrapped_f
    return wrap

def __matches_role(context, role):
    if role == 'all':
        return True
    if role == 'none':
        return False
    return context.project.has_role(context.user.id, role)

