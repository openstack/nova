#   Copyright 2011 Openstack, LLC.
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

"""The Extended Status Admin API extension."""

from webob import exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import compute
from nova import exception
from nova import flags
from nova import log as logging


FLAGS = flags.FLAGS
LOG = logging.getLogger("nova.api.openstack.compute.contrib.extendedstatus")


class ExtendedStatusController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(ExtendedStatusController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    def _get_and_extend_one(self, context, server_id, body):
        try:
            inst_ref = self.compute_api.routing_get(context, server_id)
        except exception.NotFound:
            LOG.warn("Instance %s not found" % server_id)
            raise

        for state in ['task_state', 'vm_state', 'power_state']:
            key = "%s:%s" % (Extended_status.alias, state)
            body[key] = inst_ref[state]

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']

        # Attach our slave template to the response object
        resp_obj.attach(xml=ExtendedStatusTemplate())

        try:
            self._get_and_extend_one(context, id, resp_obj.obj['server'])
        except exception.NotFound:
            explanation = _("Server not found.")
            raise exc.HTTPNotFound(explanation=explanation)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']

        # Attach our slave template to the response object
        resp_obj.attach(xml=ExtendedStatusesTemplate())

        for server in list(resp_obj.obj['servers']):
            try:
                self._get_and_extend_one(context, server['id'], server)
            except exception.NotFound:
                # NOTE(dtroyer): A NotFound exception at this point
                # happens because a delete was in progress and the
                # server that was present in the original call to
                # compute.api.get_all() is no longer present.
                # Delete it from the response and move on.
                resp_obj.obj['servers'].remove(server)
                continue


class Extended_status(extensions.ExtensionDescriptor):
    """Extended Status support"""

    name = "ExtendedStatus"
    alias = "OS-EXT-STS"
    namespace = "http://docs.openstack.org/compute/ext/" \
                "extended_status/api/v1.1"
    updated = "2011-11-03T00:00:00+00:00"
    admin_only = True

    def get_controller_extensions(self):
        controller = ExtendedStatusController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]


def make_server(elem):
    elem.set('{%s}task_state' % Extended_status.namespace,
             '%s:task_state' % Extended_status.alias)
    elem.set('{%s}power_state' % Extended_status.namespace,
             '%s:power_state' % Extended_status.alias)
    elem.set('{%s}vm_state' % Extended_status.namespace,
             '%s:vm_state' % Extended_status.alias)


class ExtendedStatusTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('server', selector='server')
        make_server(root)
        return xmlutil.SlaveTemplate(root, 1, nsmap={
            Extended_status.alias: Extended_status.namespace})


class ExtendedStatusesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('servers')
        elem = xmlutil.SubTemplateElement(root, 'server', selector='servers')
        make_server(elem)
        return xmlutil.SlaveTemplate(root, 1, nsmap={
            Extended_status.alias: Extended_status.namespace})
