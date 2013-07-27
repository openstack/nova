# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
from nova.openstack.common.gettextutils import _

ALIAS = "os-scheduler-hints"


class SchedulerHintsController(wsgi.Controller):

    @staticmethod
    def _extract_scheduler_hints(body):
        hints = {}

        attr = '%s:scheduler_hints' % ALIAS
        try:
            if attr in body:
                hints.update(body[attr])
        # Fail if non-dict provided
        except ValueError:
            msg = _("Malformed scheduler_hints attribute")
            raise webob.exc.HTTPBadRequest(reason=msg)

        return hints

    @wsgi.extends
    def create(self, req, body):
        hints = self._extract_scheduler_hints(body)

        if 'server' in body:
            body['server']['scheduler_hints'] = hints
        yield


class SchedulerHints(extensions.V3APIExtensionBase):
    """Pass arbitrary key/value pairs to the scheduler."""

    name = "SchedulerHints"
    alias = ALIAS
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "scheduler-hints/api/v3")
    version = 1

    def __init__(self, extension_info):
        super(SchedulerHints, self).__init__(extension_info)
        self.xml_deserializer = wsgi.XMLDeserializer()

    def get_controller_extensions(self):
        controller = SchedulerHintsController()
        ext = extensions.ControllerExtension(self, 'servers', controller)
        return [ext]

    def get_resources(self):
        return []

    def server_create(self, server_dict, create_kwargs):
        create_kwargs['scheduler_hints'] = server_dict.get('scheduler_hints')

    def server_xml_extract_server_deserialize(self, server_node, server_dict):
        scheduler_hints = self._extract_scheduler_hints(server_node)
        if scheduler_hints:
            server_dict[ALIAS + ':scheduler_hints'] = scheduler_hints

    def _extract_scheduler_hints(self, server_node):
        """Marshal the scheduler hints attribute of a parsed request."""
        node = self.xml_deserializer.find_first_child_named_in_namespace(
            server_node,
            "http://docs.openstack.org/compute/ext/scheduler-hints/api/v3",
            "scheduler_hints")
        if node:
            scheduler_hints = {}
            for child in self.xml_deserializer.extract_elements(node):
                scheduler_hints.setdefault(child.nodeName, [])
                value = self.xml_deserializer.extract_text(child).strip()
                scheduler_hints[child.nodeName].append(value)
            return scheduler_hints
        else:
            return None
