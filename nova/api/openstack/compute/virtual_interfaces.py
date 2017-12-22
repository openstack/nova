# Copyright (C) 2011 Midokura KK
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

"""The virtual interfaces extension."""

import webob

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack import wsgi
from nova import compute
from nova.i18n import _
from nova import network
from nova.policies import virtual_interfaces as vif_policies


def _translate_vif_summary_view(req, vif):
    """Maps keys for VIF summary view."""
    d = {}
    d['id'] = vif.uuid
    d['mac_address'] = vif.address
    if api_version_request.is_supported(req, min_version='2.12'):
        d['net_id'] = vif.net_uuid
    # NOTE(gmann): This is for v2.1 compatible mode where response should be
    # same as v2 one.
    if req.is_legacy_v2():
        d['OS-EXT-VIF-NET:net_id'] = vif.net_uuid
    return d


class ServerVirtualInterfaceController(wsgi.Controller):
    """The instance VIF API controller for the OpenStack API.

       This API is deprecated from the Microversion '2.44'.
    """

    def __init__(self):
        self.compute_api = compute.API()
        self.network_api = network.API()
        super(ServerVirtualInterfaceController, self).__init__()

    def _items(self, req, server_id, entity_maker):
        """Returns a list of VIFs, transformed through entity_maker."""
        context = req.environ['nova.context']
        context.can(vif_policies.BASE_POLICY_NAME)
        instance = common.get_instance(self.compute_api, context, server_id)

        try:
            vifs = self.network_api.get_vifs_by_instance(context, instance)
        except NotImplementedError:
            msg = _('Listing virtual interfaces is not supported by this '
                    'cloud.')
            raise webob.exc.HTTPBadRequest(explanation=msg)
        limited_list = common.limited(vifs, req)
        res = [entity_maker(req, vif) for vif in limited_list]
        return {'virtual_interfaces': res}

    @wsgi.Controller.api_version("2.1", "2.43")
    @wsgi.expected_errors((400, 404))
    def index(self, req, server_id):
        """Returns the list of VIFs for a given instance."""
        return self._items(req, server_id,
                           entity_maker=_translate_vif_summary_view)
