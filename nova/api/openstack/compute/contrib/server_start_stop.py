# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Midokura Japan K.K.
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

import webob

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova import exception
from nova import log as logging


LOG = logging.getLogger(__name__)


class ServerStartStopActionController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(ServerStartStopActionController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    def _get_instance(self, context, instance_uuid):
        try:
            return self.compute_api.get(context, instance_uuid)
        except exception.NotFound:
            msg = _("Instance not found")
            raise webob.exc.HTTPNotFound(explanation=msg)

    @wsgi.action('os-start')
    def _start_server(self, req, id, body):
        """Start an instance. """
        context = req.environ['nova.context']
        LOG.debug(_("start instance %r"), id)
        instance = self._get_instance(context, id)
        self.compute_api.start(context, instance)
        return webob.Response(status_int=202)

    @wsgi.action('os-stop')
    def _stop_server(self, req, id, body):
        """Stop an instance."""
        context = req.environ['nova.context']
        LOG.debug(_("stop instance %r"), id)
        instance = self._get_instance(context, id)
        self.compute_api.stop(context, instance)
        return webob.Response(status_int=202)


class Server_start_stop(extensions.ExtensionDescriptor):
    """Start/Stop instance compute API support"""

    name = "ServerStartStop"
    alias = "os-server-start-stop"
    namespace = "http://docs.openstack.org/compute/ext/servers/api/v1.1"
    updated = "2012-01-23:00:00+00:00"

    def get_controller_extensions(self):
        controller = ServerStartStopActionController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]
