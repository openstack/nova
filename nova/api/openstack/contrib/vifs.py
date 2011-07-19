# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2011 Midokura KK
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
from webob import exc

from nova import exception
from nova import network
from nova.api.openstack import extensions


def _translate_vif_view(vif):
    result = {'id': vif['id'],
              'mac': vif['address'],
              'network_id': vif['network_id']}
    return {'vif': result}


def _translate_vifs_view(vifs):
    return {'vifs': [_translate_vif_view(vif) for vif in vifs]}


class ServerVIFController(object):
    """The controller for VIFs attached to servers.

    A child resource of the server.
    """

    _serialization_metadata = {
        'application/xml': {
            "attributes": {
                "vif": [
                    "id",
                    "mac",
                    "network_id",
                    ]}}}

    def __init__(self):
        self.network_api = network.API()
        super(ServerVIFController, self).__init__()

    def index(self, req, server_id):
        """Return data about the vifs of the server."""
        context = req.environ['nova.context']

        vifs = self.network_api.get_vifs_by_instance(context, server_id)

        return _translate_vifs_view(vifs)


class VIFs(extensions.ExtensionDescriptor):
    def get_name(self):
        return "VIFs"

    def get_alias(self):
        return "os-vifs"

    def get_description(self):
        return "VIF support"

    def get_namespace(self):
        return "http://docs.openstack.org/ext/vifs/api/v1.1"

    def get_updated(self):
        return "2011-07-11T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension('os-server_vifs',
                         ServerVIFController())
        resources.append(res)

        return resources
