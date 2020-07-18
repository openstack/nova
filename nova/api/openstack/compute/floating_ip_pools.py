# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
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

from nova.api.openstack.api_version_request \
    import MAX_PROXY_API_SUPPORT_VERSION
from nova.api.openstack import wsgi
from nova.network import neutron
from nova.policies import floating_ip_pools as fip_policies


def _translate_floating_ip_view(pool):
    return {
        'name': pool['name'] or pool['id'],
    }


def _translate_floating_ip_pools_view(pools):
    return {
        'floating_ip_pools': [_translate_floating_ip_view(pool)
                              for pool in pools]
    }


class FloatingIPPoolsController(wsgi.Controller):
    """The Floating IP Pool API controller for the OpenStack API."""

    def __init__(self):
        super(FloatingIPPoolsController, self).__init__()
        self.network_api = neutron.API()

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors(())
    def index(self, req):
        """Return a list of pools."""
        context = req.environ['nova.context']
        context.can(fip_policies.BASE_POLICY_NAME, target={})
        pools = self.network_api.get_floating_ip_pools(context)
        return _translate_floating_ip_pools_view(pools)
