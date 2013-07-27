# Copyright 2011 OpenStack Foundation
# All Rights Reserved.
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

"""The multinic extension."""

import webob
from webob import exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)
ALIAS = "os-multinic"
authorize = extensions.extension_authorizer('compute', 'v3:' + ALIAS)


class MultinicController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(MultinicController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    def _get_instance(self, context, instance_id):
        try:
            return self.compute_api.get(context, instance_id)
        except exception.InstanceNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

    @wsgi.action('add_fixed_ip')
    def _add_fixed_ip(self, req, id, body):
        """Adds an IP on a given network to an instance."""
        context = req.environ['nova.context']
        authorize(context)

        # Validate the input entity
        if 'network_id' not in body['add_fixed_ip']:
            msg = _("Missing 'network_id' argument for add_fixed_ip")
            raise exc.HTTPBadRequest(explanation=msg)

        instance = self._get_instance(context, id)
        network_id = body['add_fixed_ip']['network_id']
        self.compute_api.add_fixed_ip(context, instance, network_id)
        return webob.Response(status_int=202)

    @wsgi.action('remove_fixed_ip')
    def _remove_fixed_ip(self, req, id, body):
        """Removes an IP from an instance."""
        context = req.environ['nova.context']
        authorize(context)

        # Validate the input entity
        if 'address' not in body['remove_fixed_ip']:
            msg = _("Missing 'address' argument for remove_fixed_ip")
            raise exc.HTTPBadRequest(explanation=msg)

        instance = self._get_instance(context, id)
        address = body['remove_fixed_ip']['address']

        try:
            self.compute_api.remove_fixed_ip(context, instance, address)
        except exception.FixedIpNotFoundForSpecificInstance as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        return webob.Response(status_int=202)


# Note: The class name is as it has to be for this to be loaded as an
# extension--only first character capitalized.
class Multinic(extensions.V3APIExtensionBase):
    """Multiple network support."""

    name = "Multinic"
    alias = ALIAS
    namespace = "http://docs.openstack.org/compute/ext/multinic/api/v3"
    version = 1

    def get_controller_extensions(self):
        controller = MultinicController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

    def get_resources(self):
        return []
