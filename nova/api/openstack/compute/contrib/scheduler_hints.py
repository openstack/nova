# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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
#    under the License

import webob.exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
import nova.log as logging

LOG = logging.getLogger(__name__)


class SchedulerHintsController(wsgi.Controller):

    @staticmethod
    def _extract_scheduler_hints(body):
        hints = {}

        try:
            hints.update(body['os:scheduler_hints'])

        # Ignore if data is not present
        except KeyError:
            pass

        # Fail if non-dict provided
        except ValueError:
            msg = _("Malformed scheduler_hints attribute")
            raise webob.exc.HTTPBadRequest(reason=msg)

        return hints

    @wsgi.extends
    def create(self, req, body):
        hints = self._extract_scheduler_hints(body)
        body['server']['scheduler_hints'] = hints
        yield


class Scheduler_hints(extensions.ExtensionDescriptor):
    """Pass arbitrary key/value pairs to the scheduler"""

    name = "SchedulerHints"
    alias = "os-scheduler-hints"
    namespace = "http://docs.openstack.org/compute/ext/" \
                "scheduler-hints/api/v2"
    updated = "2011-07-19T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = SchedulerHintsController()
        ext = extensions.ControllerExtension(self, 'servers', controller)
        return [ext]
