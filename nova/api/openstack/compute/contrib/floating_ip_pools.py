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

from nova.api.openstack import extensions
from nova import network


authorize = extensions.extension_authorizer('compute', 'floating_ip_pools')


def _translate_floating_ip_view(pool_name):
    return {
        'name': pool_name,
    }


def _translate_floating_ip_pools_view(pools):
    return {
        'floating_ip_pools': [_translate_floating_ip_view(pool_name)
                              for pool_name in pools]
    }


class FloatingIPPoolsController(object):
    """The Floating IP Pool API controller for the OpenStack API."""

    def __init__(self):
        self.network_api = network.API()
        super(FloatingIPPoolsController, self).__init__()

    def index(self, req):
        """Return a list of pools."""
        context = req.environ['nova.context']
        authorize(context)
        pools = self.network_api.get_floating_ip_pools(context)
        return _translate_floating_ip_pools_view(pools)


class Floating_ip_pools(extensions.ExtensionDescriptor):
    """Floating IPs support."""

    name = "FloatingIpPools"
    alias = "os-floating-ip-pools"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "floating_ip_pools/api/v1.1")
    updated = "2012-01-04T00:00:00Z"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-floating-ip-pools',
                         FloatingIPPoolsController(),
                         member_actions={})
        resources.append(res)

        return resources
