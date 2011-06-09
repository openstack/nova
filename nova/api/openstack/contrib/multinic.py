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

from nova import compute
from nova import log as logging
from nova.api.openstack import extensions
from nova.api.openstack import faults


LOG = logging.getLogger("nova.api.multinic")


class Multinic(extensions.ExtensionDescriptor):
    def __init__(self, *args, **kwargs):
        super(Multinic, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    def get_name(self):
        return "Multinic"

    def get_alias(self):
        return "NMN"

    def get_description(self):
        return "Multiple network support"

    def get_namespace(self):
        return "http://docs.openstack.org/ext/multinic/api/v1.1"

    def get_updated(self):
        return "2011-06-09T00:00:00+00:00"

    def get_actions(self):
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
        return exc.HTTPAccepted()

    def _remove_fixed_ip(self, input_dict, req, id):
        # Not yet implemented
        raise faults.Fault(exc.HTTPNotImplemented())
