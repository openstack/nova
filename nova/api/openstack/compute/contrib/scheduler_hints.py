# Copyright 2011 OpenStack Foundation
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

import webob.exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.i18n import _


class SchedulerHintsController(wsgi.Controller):

    @staticmethod
    def _extract_scheduler_hints(body):
        hints = {}

        attr = '%s:scheduler_hints' % Scheduler_hints.alias
        try:
            if 'os:scheduler_hints' in body:
                # NOTE(vish): This is for legacy support
                hints.update(body['os:scheduler_hints'])
            elif attr in body:
                hints.update(body[attr])
        # Fail if non-dict provided
        except ValueError:
            msg = _("Malformed scheduler_hints attribute")
            raise webob.exc.HTTPBadRequest(explanation=msg)

        return hints

    @wsgi.extends
    def create(self, req, body):
        hints = self._extract_scheduler_hints(body)

        if 'server' in body:
            body['server']['scheduler_hints'] = hints
        yield


class Scheduler_hints(extensions.ExtensionDescriptor):
    """Pass arbitrary key/value pairs to the scheduler."""

    name = "SchedulerHints"
    alias = "OS-SCH-HNT"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "scheduler-hints/api/v2")
    updated = "2011-07-19T00:00:00Z"

    def get_controller_extensions(self):
        controller = SchedulerHintsController()
        ext = extensions.ControllerExtension(self, 'servers', controller)
        return [ext]
