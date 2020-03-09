# Copyright 2011 OpenStack Foundation
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

"""The deferred instance delete extension."""

import webob

from nova.api.openstack import common
from nova.api.openstack import wsgi
from nova.compute import api as compute
from nova import exception
from nova.policies import deferred_delete as dd_policies


class DeferredDeleteController(wsgi.Controller):
    def __init__(self):
        super(DeferredDeleteController, self).__init__()
        self.compute_api = compute.API()

    @wsgi.response(202)
    @wsgi.expected_errors((403, 404, 409))
    @wsgi.action('restore')
    def _restore(self, req, id, body):
        """Restore a previously deleted instance."""
        context = req.environ["nova.context"]
        instance = common.get_instance(self.compute_api, context, id)
        context.can(dd_policies.BASE_POLICY_NAME % 'restore',
                    target={'project_id': instance.project_id})
        try:
            self.compute_api.restore(context, instance)
        except exception.QuotaError as error:
            raise webob.exc.HTTPForbidden(explanation=error.format_message())
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'restore', id)

    @wsgi.response(202)
    @wsgi.expected_errors((404, 409))
    @wsgi.action('forceDelete')
    def _force_delete(self, req, id, body):
        """Force delete of instance before deferred cleanup."""
        context = req.environ["nova.context"]
        instance = common.get_instance(self.compute_api, context, id)
        context.can(dd_policies.BASE_POLICY_NAME % 'force',
                    target={'user_id': instance.user_id,
                            'project_id': instance.project_id})
        try:
            self.compute_api.force_delete(context, instance)
        except exception.InstanceNotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.format_message())
        except exception.InstanceIsLocked as e:
            raise webob.exc.HTTPConflict(explanation=e.format_message())
