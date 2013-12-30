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

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import exception
from nova import network
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('compute', 'networks_associate')


class NetworkAssociateActionController(wsgi.Controller):
    """Network Association API Controller."""

    def __init__(self, network_api=None):
        self.network_api = network_api or network.API()

    @wsgi.action("disassociate_host")
    def _disassociate_host_only(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context)
        LOG.debug(_("Disassociating host with network with id %s"), id)
        try:
            self.network_api.associate(context, id, host=None)
        except exception.NetworkNotFound:
            raise exc.HTTPNotFound(_("Network not found"))
        return exc.HTTPAccepted()

    @wsgi.action("disassociate_project")
    def _disassociate_project_only(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context)
        LOG.debug(_("Disassociating project with network with id %s"), id)
        try:
            self.network_api.associate(context, id, project=None)
        except exception.NetworkNotFound:
            raise exc.HTTPNotFound(_("Network not found"))
        return exc.HTTPAccepted()

    @wsgi.action("associate_host")
    def _associate_host(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context)

        try:
            self.network_api.associate(context, id,
                                       host=body['associate_host'])
        except exception.NetworkNotFound:
            raise exc.HTTPNotFound(_("Network not found"))
        return exc.HTTPAccepted()


class Networks_associate(extensions.ExtensionDescriptor):
    """Network association support."""

    name = "NetworkAssociationSupport"
    alias = "os-networks-associate"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "networks_associate/api/v2")
    updated = "2012-11-19T00:00:00+00:00"

    def get_controller_extensions(self):
        extension = extensions.ControllerExtension(
                self, 'os-networks', NetworkAssociateActionController())

        return [extension]
