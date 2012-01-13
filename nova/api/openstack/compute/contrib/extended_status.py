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
from nova.api.openstack import xmlutil
from nova import compute
from nova import exception
from nova import flags
from nova import log as logging


FLAGS = flags.FLAGS
LOG = logging.getLogger("nova.api.openstack.compute.contrib.extendedstatus")


class Extended_status(extensions.ExtensionDescriptor):
    """Extended Status support"""

    name = "ExtendedStatus"
    alias = "OS-EXT-STS"
    namespace = "http://docs.openstack.org/compute/ext/" \
                "extended_status/api/v1.1"
    updated = "2011-11-03T00:00:00+00:00"
    admin_only = True

    def get_request_extensions(self):
        request_extensions = []

        def _get_and_extend_one(context, server_id, body):
            compute_api = compute.API()
            try:
                inst_ref = compute_api.routing_get(context, server_id)
            except exception.NotFound:
                LOG.warn("Instance %s not found (one)" % server_id)
                explanation = _("Server not found.")
                raise exc.HTTPNotFound(explanation=explanation)

            for state in ['task_state', 'vm_state', 'power_state']:
                key = "%s:%s" % (Extended_status.alias, state)
                body['server'][key] = inst_ref[state]

        def _get_and_extend_all(context, body):
            # TODO(mdietz): This is a brilliant argument for this to *not*
            # be an extension. The problem is we either have to 1) duplicate
            # the logic from the servers controller or 2) do what we did
            # and iterate over the list of potentially sorted, limited
            # and whatever else elements and find each individual.
            compute_api = compute.API()

            for server in list(body['servers']):
                try:
                    inst_ref = compute_api.routing_get(context, server['id'])
                except exception.NotFound:
                    # NOTE(dtroyer): A NotFound exception at this point
                    # happens because a delete was in progress and the
                    # server that was present in the original call to
                    # compute.api.get_all() is no longer present.
                    # Delete it from the response and move on.
                    LOG.warn("Instance %s not found (all)" % server['id'])
                    body['servers'].remove(server)
                    continue

                #TODO(bcwaldon): these attributes should be prefixed with
                # something specific to this extension
                for state in ['task_state', 'vm_state', 'power_state']:
                    key = "%s:%s" % (Extended_status.alias, state)
                    server[key] = inst_ref[state]

        def _extended_status_handler(req, res, body):
            context = req.environ['nova.context']
            server_id = req.environ['wsgiorg.routing_args'][1].get('id')

            if 'nova.template' in req.environ:
                tmpl = req.environ['nova.template']
                tmpl.attach(ExtendedStatusTemplate())

            if server_id:
                _get_and_extend_one(context, server_id, body)
            else:
                _get_and_extend_all(context, body)
            return res

        req_ext = extensions.RequestExtension('GET',
                                '/:(project_id)/servers/:(id)',
                                _extended_status_handler)
        request_extensions.append(req_ext)

        return request_extensions


class ExtendedStatusTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('server')
        root.set('{%s}task_state' % Extended_status.namespace,
                 '%s:task_state' % Extended_status.alias)
        root.set('{%s}power_state' % Extended_status.namespace,
                 '%s:power_state' % Extended_status.alias)
        root.set('{%s}vm_state' % Extended_status.namespace,
                 '%s:vm_state' % Extended_status.alias)
        return xmlutil.SlaveTemplate(root, 1, nsmap={
            Extended_status.alias: Extended_status.namespace})
