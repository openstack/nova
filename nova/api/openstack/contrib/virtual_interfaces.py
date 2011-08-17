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

from webob import exc
import webob

from nova import compute
from nova import exception
from nova import log as logging
from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import faults
from nova.api.openstack import wsgi


LOG = logging.getLogger("nova.api.virtual_interfaces")


def _translate_vif_summary_view(_context, vif):
    """Maps keys for VIF summary view."""
    d = {}
    d['id'] = vif['uuid']
    d['mac_address'] = vif['address']
    return d


def _get_metadata():
    metadata = {
        "attributes": {
                'virtual_interface': ["id", "mac_address"]}}
    return metadata


class ServerVirtualInterfaceController(object):
    """The instance VIF API controller for the Openstack API.
    """

    def __init__(self):
        self.compute_api = compute.API()
        super(ServerVirtualInterfaceController, self).__init__()

    def _items(self, req, server_id, entity_maker):
        """Returns a list of VIFs, transformed through entity_maker."""
        context = req.environ['nova.context']

        try:
            instance = self.compute_api.get(context, server_id)
        except exception.NotFound:
            return faults.Fault(exc.HTTPNotFound())

        vifs = instance['virtual_interfaces']
        limited_list = common.limited(vifs, req)
        res = [entity_maker(context, vif) for vif in limited_list]
        return {'virtual_interfaces': res}

    def index(self, req, server_id):
        """Returns the list of VIFs for a given instance."""
        return self._items(req, server_id,
                           entity_maker=_translate_vif_summary_view)


class Virtual_interfaces(extensions.ExtensionDescriptor):

    def get_name(self):
        return "VirtualInterfaces"

    def get_alias(self):
        return "virtual_interfaces"

    def get_description(self):
        return "Virtual interface support"

    def get_namespace(self):
        return "http://docs.openstack.org/ext/virtual_interfaces/api/v1.1"

    def get_updated(self):
        return "2011-08-17T00:00:00+00:00"

    def get_resources(self):
        resources = []

        metadata = _get_metadata()
        body_serializers = {
            'application/xml': wsgi.XMLDictSerializer(metadata=metadata,
                                                      xmlns=wsgi.XMLNS_V11)}
        serializer = wsgi.ResponseSerializer(body_serializers, None)
        res = extensions.ResourceExtension(
            'os-virtual-interfaces',
            controller=ServerVirtualInterfaceController(),
            parent=dict(member_name='server', collection_name='servers'),
            serializer=serializer)
        resources.append(res)

        return resources
