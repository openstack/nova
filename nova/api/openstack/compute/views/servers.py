# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack LLC.
# Copyright 2011 Piston Cloud Computing, Inc.
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

import hashlib

from nova.api.openstack import common
from nova.api.openstack.compute.views import addresses as views_addresses
from nova.api.openstack.compute.views import flavors as views_flavors
from nova.api.openstack.compute.views import images as views_images
from nova import log as logging
from nova import utils


LOG = logging.getLogger('nova.api.openstack.compute.views.servers')


class ViewBuilder(common.ViewBuilder):
    """Model a server API response as a python dictionary."""

    _collection_name = "servers"

    _progress_statuses = (
        "ACTIVE",
        "BUILD",
        "REBUILD",
        "RESIZE",
        "VERIFY_RESIZE",
    )

    _fault_statuses = (
        "ERROR",
    )

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()
        self._address_builder = views_addresses.ViewBuilder()
        self._flavor_builder = views_flavors.ViewBuilder()
        self._image_builder = views_images.ViewBuilder()

    def _skip_precooked(func):
        def wrapped(self, request, instance):
            if instance.get("_is_precooked"):
                return dict(server=instance)
            else:
                return func(self, request, instance)
        return wrapped

    def create(self, request, instance):
        """View that should be returned when an instance is created."""
        return {
            "server": {
                "id": instance["uuid"],
                "links": self._get_links(request, instance["uuid"]),
            },
        }

    @_skip_precooked
    def basic(self, request, instance):
        """Generic, non-detailed view of an instance."""
        return {
            "server": {
                "id": instance["uuid"],
                "name": instance["display_name"],
                "links": self._get_links(request, instance["uuid"]),
            },
        }

    @_skip_precooked
    def show(self, request, instance):
        """Detailed view of a single instance."""
        server = {
            "server": {
                "id": instance["uuid"],
                "name": instance["display_name"],
                "status": self._get_vm_state(instance),
                "tenant_id": instance.get("project_id") or "",
                "user_id": instance.get("user_id") or "",
                "metadata": self._get_metadata(instance),
                "hostId": self._get_host_id(instance) or "",
                "image": self._get_image(request, instance),
                "flavor": self._get_flavor(request, instance),
                "created": utils.isotime(instance["created_at"]),
                "updated": utils.isotime(instance["updated_at"]),
                "addresses": self._get_addresses(request, instance),
                "accessIPv4": instance.get("access_ip_v4") or "",
                "accessIPv6": instance.get("access_ip_v6") or "",
                "key_name": instance.get("key_name") or "",
                "config_drive": instance.get("config_drive"),
                "links": self._get_links(request, instance["uuid"]),
            },
        }
        _inst_fault = self._get_fault(request, instance)
        if server["server"]["status"] in self._fault_statuses and _inst_fault:
            server['server']['fault'] = _inst_fault

        if server["server"]["status"] in self._progress_statuses:
            server["server"]["progress"] = instance.get("progress", 0)

        return server

    def index(self, request, instances):
        """Show a list of servers without many details."""
        return self._list_view(self.basic, request, instances)

    def detail(self, request, instances):
        """Detailed view of a list of instance."""
        return self._list_view(self.show, request, instances)

    def _list_view(self, func, request, servers):
        """Provide a view for a list of servers."""
        server_list = [func(request, server)["server"] for server in servers]
        servers_links = self._get_collection_links(request, servers)
        servers_dict = dict(servers=server_list)

        if servers_links:
            servers_dict["servers_links"] = servers_links

        return servers_dict

    @staticmethod
    def _get_metadata(instance):
        metadata = instance.get("metadata", [])
        return dict((item['key'], str(item['value'])) for item in metadata)

    @staticmethod
    def _get_vm_state(instance):
        return common.status_from_state(instance.get("vm_state"),
                                        instance.get("task_state"))

    @staticmethod
    def _get_host_id(instance):
        host = instance.get("host")
        if host:
            return hashlib.sha224(host).hexdigest()  # pylint: disable=E1101

    def _get_addresses(self, request, instance):
        context = request.environ["nova.context"]
        networks = common.get_networks_for_instance(context, instance)
        return self._address_builder.index(networks)["addresses"]

    def _get_image(self, request, instance):
        image_ref = instance["image_ref"]
        image_id = str(common.get_id_from_href(image_ref))
        bookmark = self._image_builder._get_bookmark_link(request, image_id)
        return {
            "id": image_id,
            "links": [{
                "rel": "bookmark",
                "href": bookmark,
            }],
        }

    def _get_flavor(self, request, instance):
        flavor_id = instance["instance_type"]["flavorid"]
        flavor_ref = self._flavor_builder._get_href_link(request, flavor_id)
        flavor_bookmark = self._flavor_builder._get_bookmark_link(request,
                                                                  flavor_id)
        return {
            "id": str(common.get_id_from_href(flavor_ref)),
            "links": [{
                "rel": "bookmark",
                "href": flavor_bookmark,
            }],
        }

    def _get_fault(self, request, instance):
        fault = instance.get("fault", None)

        if not fault:
            return None

        return {
            "code": fault["code"],
            "created": utils.isotime(fault["created_at"]),
            "message": fault["message"],
            "details": fault["details"],
        }
