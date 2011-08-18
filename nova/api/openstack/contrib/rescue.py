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

from nova import compute
from nova import log as logging
from nova.api.openstack import extensions as exts
from nova.api.openstack import faults

LOG = logging.getLogger("nova.api.contrib.rescue")


class Rescue(exts.ExtensionDescriptor):
    """The Rescue API controller for the OpenStack API."""
    def __init__(self):
        super(Rescue, self).__init__()
        self.compute_api = compute.API()

    def _rescue(self, input_dict, req, instance_id):
        """Enable or disable rescue mode."""
        context = req.environ["nova.context"]
        action = input_dict["rescue"]["action"]

        try:
            if action == "rescue":
                self.compute_api.rescue(context, instance_id)
            elif action == "unrescue":
                self.compute_api.unrescue(context, instance_id)
        except Exception, e:
            LOG.exception(_("Error in %(action)s: %(e)s") % locals())
            return faults.Fault(exc.HTTPBadRequest())

        return webob.Response(status_int=202)

    def get_name(self):
        return "Rescue"

    def get_alias(self):
        return "rescue"

    def get_description(self):
        return "Instance rescue mode"

    def get_namespace(self):
        return "http://docs.openstack.org/ext/rescue/api/v1.1"

    def get_updated(self):
        return "2011-08-18T00:00:00+00:00"

    def get_actions(self):
        """Return the actions the extension adds, as required by contract."""
        actions = [
                exts.ActionExtension("servers", "rescue", self._rescue),
                exts.ActionExtension("servers", "unrescue", self._rescue),
        ]

        return actions
