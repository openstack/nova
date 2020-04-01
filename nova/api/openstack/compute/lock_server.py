# Copyright 2011 OpenStack Foundation
# Copyright 2013 IBM Corp.
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import lock_server
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import api as compute
from nova.policies import lock_server as ls_policies


class LockServerController(wsgi.Controller):
    def __init__(self):
        super(LockServerController, self).__init__()
        self.compute_api = compute.API()

    @wsgi.response(202)
    @wsgi.expected_errors(404)
    @wsgi.action('lock')
    @validation.schema(lock_server.lock_v2_73, "2.73")
    def _lock(self, req, id, body):
        """Lock a server instance."""
        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, id)
        context.can(ls_policies.POLICY_ROOT % 'lock',
                    target={'user_id': instance.user_id,
                            'project_id': instance.project_id})
        reason = None
        if (api_version_request.is_supported(req, min_version='2.73') and
            body['lock'] is not None):
            reason = body['lock'].get('locked_reason')
        self.compute_api.lock(context, instance, reason=reason)

    @wsgi.response(202)
    @wsgi.expected_errors(404)
    @wsgi.action('unlock')
    def _unlock(self, req, id, body):
        """Unlock a server instance."""
        context = req.environ['nova.context']
        instance = common.get_instance(self.compute_api, context, id)
        context.can(ls_policies.POLICY_ROOT % 'unlock',
                    target={'project_id': instance.project_id})
        if not self.compute_api.is_expected_locked_by(context, instance):
            context.can(ls_policies.POLICY_ROOT % 'unlock:unlock_override',
                        target={'project_id': instance.project_id})

        self.compute_api.unlock(context, instance)
