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

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute

ALIAS = "os-lock-server"

authorize = extensions.os_compute_authorizer(ALIAS)


class LockServerController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(LockServerController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API(skip_policy_check=True)

    @wsgi.response(202)
    @extensions.expected_errors(404)
    @wsgi.action('lock')
    def _lock(self, req, id, body):
        """Lock a server instance."""
        context = req.environ['nova.context']
        authorize(context, action='lock')
        instance = common.get_instance(self.compute_api, context, id)
        self.compute_api.lock(context, instance)

    @wsgi.response(202)
    @extensions.expected_errors(404)
    @wsgi.action('unlock')
    def _unlock(self, req, id, body):
        """Unlock a server instance."""
        context = req.environ['nova.context']
        authorize(context, action='unlock')
        instance = common.get_instance(self.compute_api, context, id)
        if not self.compute_api.is_expected_locked_by(context, instance):
            authorize(context, target=instance,
                      action='unlock:unlock_override')

        self.compute_api.unlock(context, instance)


class LockServer(extensions.V21APIExtensionBase):
    """Enable lock/unlock server actions."""

    name = "LockServer"
    alias = ALIAS
    version = 1

    def get_controller_extensions(self):
        controller = LockServerController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

    def get_resources(self):
        return []
