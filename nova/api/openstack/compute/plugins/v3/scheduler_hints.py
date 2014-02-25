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
from nova.openstack.common.gettextutils import _

ALIAS = "os-scheduler-hints"


class SchedulerHints(extensions.V3APIExtensionBase):
    """Pass arbitrary key/value pairs to the scheduler."""

    name = "SchedulerHints"
    alias = ALIAS
    version = 1

    def get_controller_extensions(self):
        return []

    def get_resources(self):
        return []

    def server_create(self, server_dict, create_kwargs):
        scheduler_hints = server_dict.get(ALIAS + ':scheduler_hints', {})
        if not isinstance(scheduler_hints, dict):
            msg = _("Malformed scheduler_hints attribute")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        create_kwargs['scheduler_hints'] = scheduler_hints
