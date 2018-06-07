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

from oslo_context import context
from oslo_db.sqlalchemy import enginefacade

from nova.api.openstack.placement import exception
from nova.api.openstack.placement import policy


@enginefacade.transaction_context_provider
class RequestContext(context.RequestContext):

    def can(self, action, target=None, fatal=True):
        """Verifies that the given action is valid on the target in this
        context.

        :param action: string representing the action to be checked.
        :param target: As much information about the object being operated on
            as possible. The target argument should be a dict instance or an
            instance of a class that fully supports the Mapping abstract base
            class and deep copying. For object creation this should be a
            dictionary representing the location of the object e.g.
            ``{'project_id': context.project_id}``. If None, then this default
            target will be considered::

                {'project_id': self.project_id, 'user_id': self.user_id}
        :param fatal: if False, will return False when an
            exception.PolicyNotAuthorized occurs.
        :raises nova.api.openstack.placement.exception.PolicyNotAuthorized:
            if verification fails and fatal is True.
        :return: returns a non-False value (not necessarily "True") if
            authorized and False if not authorized and fatal is False.
        """
        if target is None:
            target = {'project_id': self.project_id,
                      'user_id': self.user_id}
        try:
            return policy.authorize(self, action, target)
        except exception.PolicyNotAuthorized:
            if fatal:
                raise
            return False
