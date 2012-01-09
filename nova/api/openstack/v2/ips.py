# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from webob import exc

import nova
from nova.api.openstack import common
from nova.api.openstack.v2.views import addresses as view_addresses
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova import log as logging
from nova import flags


LOG = logging.getLogger('nova.api.openstack.v2.ips')
FLAGS = flags.FLAGS


def make_network(elem):
    elem.set('id', 0)

    ip = xmlutil.SubTemplateElement(elem, 'ip', selector=1)
    ip.set('version')
    ip.set('addr')


network_nsmap = {None: xmlutil.XMLNS_V11}


class NetworkTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        sel = xmlutil.Selector(xmlutil.get_items, 0)
        root = xmlutil.TemplateElement('network', selector=sel)
        make_network(root)
        return xmlutil.MasterTemplate(root, 1, nsmap=network_nsmap)


class AddressesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('addresses', selector='addresses')
        elem = xmlutil.SubTemplateElement(root, 'network',
                                          selector=xmlutil.get_items)
        make_network(elem)
        return xmlutil.MasterTemplate(root, 1, nsmap=network_nsmap)


class Controller(wsgi.Controller):
    """The servers addresses API controller for the Openstack API."""

    _view_builder_class = view_addresses.ViewBuilder

    def __init__(self, **kwargs):
        super(Controller, self).__init__(**kwargs)
        self._compute_api = nova.compute.API()

    def _get_instance(self, context, server_id):
        try:
            instance = self._compute_api.get(context, server_id)
        except nova.exception.NotFound:
            msg = _("Instance does not exist")
            raise exc.HTTPNotFound(explanation=msg)
        return instance

    def create(self, req, server_id, body):
        raise exc.HTTPNotImplemented()

    def delete(self, req, server_id, id):
        raise exc.HTTPNotImplemented()

    @wsgi.serializers(xml=AddressesTemplate)
    def index(self, req, server_id):
        context = req.environ["nova.context"]
        instance = self._get_instance(context, server_id)
        networks = common.get_networks_for_instance(context, instance)
        return self._view_builder.index(networks)

    @wsgi.serializers(xml=NetworkTemplate)
    def show(self, req, server_id, id):
        context = req.environ["nova.context"]
        instance = self._get_instance(context, server_id)
        networks = common.get_networks_for_instance(context, instance)

        if id not in networks:
            msg = _("Instance is not a member of specified network")
            raise exc.HTTPNotFound(explanation=msg)

        return self._view_builder.show(networks[id], id)


def create_resource():
    return wsgi.Resource(Controller())
