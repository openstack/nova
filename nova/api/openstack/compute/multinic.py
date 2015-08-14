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

from webob import exc

from nova.api.openstack import common
from nova.api.openstack.compute.schemas import multinic
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova import compute
from nova import exception


ALIAS = "os-multinic"
authorize = extensions.os_compute_authorizer(ALIAS)


class MultinicController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(MultinicController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API(skip_policy_check=True)

    @wsgi.response(202)
    @wsgi.action('addFixedIp')
    @extensions.expected_errors((400, 404))
    @validation.schema(multinic.add_fixed_ip)
    def _add_fixed_ip(self, req, id, body):
        """Adds an IP on a given network to an instance."""
        context = req.environ['nova.context']
        authorize(context)

        instance = common.get_instance(self.compute_api, context, id)
        network_id = body['addFixedIp']['networkId']
        try:
            self.compute_api.add_fixed_ip(context, instance, network_id)
        except exception.InstanceUnknownCell as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.NoMoreFixedIps as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

    @wsgi.response(202)
    @wsgi.action('removeFixedIp')
    @extensions.expected_errors((400, 404))
    @validation.schema(multinic.remove_fixed_ip)
    def _remove_fixed_ip(self, req, id, body):
        """Removes an IP from an instance."""
        context = req.environ['nova.context']
        authorize(context)

        instance = common.get_instance(self.compute_api, context, id)
        address = body['removeFixedIp']['address']

        try:
            self.compute_api.remove_fixed_ip(context, instance, address)
        except exception.InstanceUnknownCell as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.FixedIpNotFoundForSpecificInstance as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())


# Note: The class name is as it has to be for this to be loaded as an
# extension--only first character capitalized.
class Multinic(extensions.V21APIExtensionBase):
    """Multiple network support."""

    name = "Multinic"
    alias = ALIAS
    version = 1

    def get_controller_extensions(self):
        controller = MultinicController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

    def get_resources(self):
        return []
