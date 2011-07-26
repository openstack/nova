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

from webob import exc
import webob

from nova import compute
from nova import log as logging
from nova.api.openstack import extensions
from nova.api.openstack import faults


LOG = logging.getLogger("nova.api.multinic")


# Note: The class name is as it has to be for this to be loaded as an
# extension--only first character capitalized.
class Multinic(extensions.ExtensionDescriptor):
    """The multinic extension.

    Exposes addFixedIp and removeFixedIp actions on servers.

    """

    def __init__(self, *args, **kwargs):
        """Initialize the extension.

        Gets a compute.API object so we can call the back-end
        add_fixed_ip() and remove_fixed_ip() methods.
        """

        super(Multinic, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    def get_name(self):
        """Return the extension name, as required by contract."""

        return "Multinic"

    def get_alias(self):
        """Return the extension alias, as required by contract."""

        return "NMN"

    def get_description(self):
        """Return the extension description, as required by contract."""

        return "Multiple network support"

    def get_namespace(self):
        """Return the namespace, as required by contract."""

        return "http://docs.openstack.org/ext/multinic/api/v1.1"

    def get_updated(self):
        """Return the last updated timestamp, as required by contract."""

        return "2011-06-09T00:00:00+00:00"

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

    def _add_fixed_ip(self, input_dict, req, id):
        """Adds an IP on a given network to an instance."""

        try:
            # Validate the input entity
            if 'networkId' not in input_dict['addFixedIp']:
                LOG.exception(_("Missing 'networkId' argument for addFixedIp"))
                return faults.Fault(exc.HTTPUnprocessableEntity())

            # Add the fixed IP
            network_id = input_dict['addFixedIp']['networkId']
            self.compute_api.add_fixed_ip(req.environ['nova.context'], id,
                                          network_id)
        except Exception, e:
            LOG.exception(_("Error in addFixedIp %s"), e)
            return faults.Fault(exc.HTTPBadRequest())
        return webob.Response(status_int=202)

    def _remove_fixed_ip(self, input_dict, req, id):
        """Removes an IP from an instance."""

        try:
            # Validate the input entity
            if 'address' not in input_dict['removeFixedIp']:
                LOG.exception(_("Missing 'address' argument for "
                                "removeFixedIp"))
                return faults.Fault(exc.HTTPUnprocessableEntity())

            # Remove the fixed IP
            address = input_dict['removeFixedIp']['address']
            self.compute_api.remove_fixed_ip(req.environ['nova.context'], id,
                                             address)
        except Exception, e:
            LOG.exception(_("Error in removeFixedIp %s"), e)
            return faults.Fault(exc.HTTPBadRequest())
        return webob.Response(status_int=202)
