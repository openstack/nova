# vim: tabstop=4 shiftwidth=4 softtabstop=4

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
#    under the License

from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.api.openstack.v2 import extensions
from nova import log as logging
from nova import network


LOG = logging.getLogger('nova.api.openstack.v2.contrib.floating_ip_poolss')


def _translate_floating_ip_view(pool):
    return {
        'name': pool['name'],
    }


def _translate_floating_ip_pools_view(pools):
    return {
        'floating_ip_pools': [_translate_floating_ip_view(pool)
                              for pool in pools]
    }


class FloatingIPPoolsController(object):
    """The Floating IP Pool API controller for the OpenStack API."""

    def __init__(self):
        self.network_api = network.API()
        super(FloatingIPPoolsController, self).__init__()

    def index(self, req):
        """Return a list of pools."""
        context = req.environ['nova.context']
        pools = self.network_api.get_floating_ip_pools(context)
        return _translate_floating_ip_pools_view(pools)


def make_float_ip(elem):
    elem.set('name')


class FloatingIPPoolTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('floating_ip_pool',
                                       selector='floating_ip_pool')
        make_float_ip(root)
        return xmlutil.MasterTemplate(root, 1)


class FloatingIPPoolsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('floating_ip_pools')
        elem = xmlutil.SubTemplateElement(root, 'floating_ip_pool',
                                          selector='floating_ip_pools')
        make_float_ip(elem)
        return xmlutil.MasterTemplate(root, 1)


class FloatingIPPoolsSerializer(xmlutil.XMLTemplateSerializer):
    def index(self):
        return FloatingIPPoolsTemplate()


class Floating_ip_pools(extensions.ExtensionDescriptor):
    """Floating IPs support"""

    name = "Floating_ip_pools"
    alias = "os-floating-ip-pools"
    namespace = \
        "http://docs.openstack.org/compute/ext/floating_ip_pools/api/v1.1"
    updated = "2012-01-04T00:00:00+00:00"

    def get_resources(self):
        resources = []

        body_serializers = {
            'application/xml': FloatingIPPoolsSerializer(),
            }

        serializer = wsgi.ResponseSerializer(body_serializers)

        res = extensions.ResourceExtension('os-floating-ip-pools',
                         FloatingIPPoolsController(),
                         serializer=serializer,
                         member_actions={})
        resources.append(res)

        return resources
