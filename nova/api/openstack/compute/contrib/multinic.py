# Copyright 2011 OpenStack LLC.
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
from nova import compute
from nova import exception
from nova import log as logging


LOG = logging.getLogger("nova.api.openstack.compute.contrib.multinic")


# Note: The class name is as it has to be for this to be loaded as an
# extension--only first character capitalized.
class Multinic(extensions.ExtensionDescriptor):
    """Multiple network support"""

    name = "Multinic"
    alias = "NMN"
    namespace = "http://docs.openstack.org/compute/ext/multinic/api/v1.1"
    updated = "2011-06-09T00:00:00+00:00"

    def __init__(self, ext_mgr):
        """Initialize the extension.

        Gets a compute.API object so we can call the back-end
        add_fixed_ip() and remove_fixed_ip() methods.
        """

        super(Multinic, self).__init__(ext_mgr)
        self.compute_api = compute.API()

    def get_actions(self):
        """Return the actions the extension adds, as required by contract."""

        actions = []

        # Add the add_fixed_ip action
        act = extensions.ActionExtension("servers", "addFixedIp",
                                         self._add_fixed_ip)
        actions.append(act)

        # Add the remove_fixed_ip action
        act = extensions.ActionExtension("servers", "removeFixedIp",
                                         self._remove_fixed_ip)
        actions.append(act)

        return actions

    def _get_instance(self, context, instance_id):
        try:
            return self.compute_api.get(context, instance_id)
        except exception.InstanceNotFound:
            msg = _("Server not found")
            raise exc.HTTPNotFound(msg)

    def _add_fixed_ip(self, input_dict, req, id):
        """Adds an IP on a given network to an instance."""

        # Validate the input entity
        if 'networkId' not in input_dict['addFixedIp']:
            msg = _("Missing 'networkId' argument for addFixedIp")
            raise exc.HTTPUnprocessableEntity(explanation=msg)

        context = req.environ['nova.context']
        instance = self._get_instance(context, id)
        network_id = input_dict['addFixedIp']['networkId']
        self.compute_api.add_fixed_ip(context, instance, network_id)
        return webob.Response(status_int=202)

    def _remove_fixed_ip(self, input_dict, req, id):
        """Removes an IP from an instance."""

        # Validate the input entity
        if 'address' not in input_dict['removeFixedIp']:
            msg = _("Missing 'address' argument for removeFixedIp")
            raise exc.HTTPUnprocessableEntity(explanation=msg)

        context = req.environ['nova.context']
        instance = self._get_instance(context, id)
        address = input_dict['removeFixedIp']['address']

        try:
            self.compute_api.remove_fixed_ip(context, instance, address)
        except exceptions.FixedIpNotFoundForSpecificInstance:
            LOG.exception(_("Unable to find address %r") % address)
            raise exc.HTTPBadRequest()

        return webob.Response(status_int=202)
