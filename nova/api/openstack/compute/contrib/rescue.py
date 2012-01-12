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

"""The rescue mode extension."""

import webob
from webob import exc

from nova.api.openstack import extensions as exts
from nova.api.openstack import wsgi
from nova import compute
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils


FLAGS = flags.FLAGS
LOG = logging.getLogger("nova.api.openstack.compute.contrib.rescue")


class RescueController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(RescueController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    def _get_instance(self, context, instance_id):
        try:
            return self.compute_api.get(context, instance_id)
        except exception.InstanceNotFound:
            msg = _("Server not found")
            raise exc.HTTPNotFound(msg)

    @wsgi.action('rescue')
    @exts.wrap_errors
    def _rescue(self, req, id, body):
        """Rescue an instance."""
        context = req.environ["nova.context"]

        if body['rescue'] and 'adminPass' in body['rescue']:
            password = body['rescue']['adminPass']
        else:
            password = utils.generate_password(FLAGS.password_length)

        instance = self._get_instance(context, id)
        self.compute_api.rescue(context, instance, rescue_password=password)
        return {'adminPass': password}

    @wsgi.action('unrescue')
    @exts.wrap_errors
    def _unrescue(self, req, id, body):
        """Unrescue an instance."""
        context = req.environ["nova.context"]
        instance = self._get_instance(context, id)
        self.compute_api.unrescue(context, instance)
        return webob.Response(status_int=202)


class Rescue(exts.ExtensionDescriptor):
    """Instance rescue mode"""

    name = "Rescue"
    alias = "os-rescue"
    namespace = "http://docs.openstack.org/compute/ext/rescue/api/v1.1"
    updated = "2011-08-18T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = RescueController()
        extension = exts.ControllerExtension(self, 'servers', controller)
        return [extension]
