# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

from nova.api.openstack.v2 import extensions
from nova.api.openstack.v2 import servers
from nova.api.openstack.v2 import views
from nova.api.openstack import wsgi


class ViewBuilder(views.servers.ViewBuilder):
    """Adds security group output when viewing server details."""

    def show(self, request, instance):
        """Detailed view of a single instance."""
        server = super(ViewBuilder, self).show(request, instance)
        server["server"]["security_groups"] = self._get_groups(instance)
        return server

    def _get_groups(self, instance):
        """Get a list of security groups for this instance."""
        groups = instance.get('security_groups')
        if groups is not None:
            return [{"name": group["name"]} for group in groups]


class Controller(servers.Controller):
    _view_builder_class = ViewBuilder


class Createserverext(extensions.ExtensionDescriptor):
    """Extended support to the Create Server v1.1 API"""

    name = "Createserverext"
    alias = "os-create-server-ext"
    namespace = "http://docs.openstack.org/compute/ext/" \
                "createserverext/api/v1.1"
    updated = "2011-07-19T00:00:00+00:00"

    def get_resources(self):
        resources = []
        controller = Controller()

        res = extensions.ResourceExtension('os-create-server-ext',
                                           controller=controller)
        resources.append(res)

        return resources
