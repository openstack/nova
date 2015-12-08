# Copyright 2010-2011 OpenStack Foundation
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

from oslo_log import log as logging

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack.compute.views import addresses as views_addresses
from nova.api.openstack.compute.views import flavors as views_flavors
from nova.api.openstack.compute.views import images as views_images
from nova.i18n import _LW
from nova.objects import base as obj_base
from nova import utils


LOG = logging.getLogger(__name__)


class ViewBuilder(common.ViewBuilder):
    """Model a server API response as a python dictionary."""

    _collection_name = "servers"

    _progress_statuses = (
        "ACTIVE",
        "BUILD",
        "REBUILD",
        "RESIZE",
        "VERIFY_RESIZE",
        "MIGRATING",
    )

    _fault_statuses = (
        "ERROR", "DELETED"
    )

    # These are the lazy-loadable instance attributes required for showing
    # details about an instance. Add to this list as new things need to be
    # shown.
    _show_expected_attrs = ['flavor', 'info_cache', 'metadata']

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilder, self).__init__()
        self._address_builder = views_addresses.ViewBuilder()
        self._flavor_builder = views_flavors.ViewBuilder()
        self._image_builder = views_images.ViewBuilder()

    def create(self, request, instance):
        """View that should be returned when an instance is created."""
        return {
            "server": {
                "id": instance["uuid"],
                "links": self._get_links(request,
                                         instance["uuid"],
                                         self._collection_name),
            },
        }

    def basic(self, request, instance):
        """Generic, non-detailed view of an instance."""
        return {
            "server": {
                "id": instance["uuid"],
                "name": instance["display_name"],
                "links": self._get_links(request,
                                         instance["uuid"],
                                         self._collection_name),
            },
        }

    def get_show_expected_attrs(self, expected_attrs=None):
        """Returns a list of lazy-loadable expected attributes used by show

        This should be used when getting the instances from the database so
        that the necessary attributes are pre-loaded before needing to build
        the show response where lazy-loading can fail if an instance was
        deleted.

        :param list expected_attrs: The list of expected attributes that will
            be requested in addition to what this view builder requires. This
            method will merge the two lists and return what should be
            ultimately used when getting an instance from the database.
        :returns: merged and sorted list of expected attributes
        """
        if expected_attrs is None:
            expected_attrs = []
        # NOTE(mriedem): We sort the list so we can have predictable test
        # results.
        return sorted(list(set(self._show_expected_attrs + expected_attrs)))

    def show(self, request, instance):
        """Detailed view of a single instance."""
        ip_v4 = instance.get('access_ip_v4')
        ip_v6 = instance.get('access_ip_v6')
        server = {
            "server": {
                "id": instance["uuid"],
                "name": instance["display_name"],
                "status": self._get_vm_status(instance),
                "tenant_id": instance.get("project_id") or "",
                "user_id": instance.get("user_id") or "",
                "metadata": self._get_metadata(instance),
                "hostId": self._get_host_id(instance) or "",
                "image": self._get_image(request, instance),
                "flavor": self._get_flavor(request, instance),
                "created": utils.isotime(instance["created_at"]),
                "updated": utils.isotime(instance["updated_at"]),
                "addresses": self._get_addresses(request, instance),
                "accessIPv4": str(ip_v4) if ip_v4 is not None else '',
                "accessIPv6": str(ip_v6) if ip_v6 is not None else '',
                "links": self._get_links(request,
                                         instance["uuid"],
                                         self._collection_name),
            },
        }
        if server["server"]["status"] in self._fault_statuses:
            _inst_fault = self._get_fault(request, instance)
            if _inst_fault:
                server['server']['fault'] = _inst_fault

        if server["server"]["status"] in self._progress_statuses:
            server["server"]["progress"] = instance.get("progress", 0)

        return server

    def index(self, request, instances):
        """Show a list of servers without many details."""
        coll_name = self._collection_name
        return self._list_view(self.basic, request, instances, coll_name)

    def detail(self, request, instances):
        """Detailed view of a list of instance."""
        coll_name = self._collection_name + '/detail'
        return self._list_view(self.show, request, instances, coll_name)

    def _list_view(self, func, request, servers, coll_name):
        """Provide a view for a list of servers.

        :param func: Function used to format the server data
        :param request: API request
        :param servers: List of servers in dictionary format
        :param coll_name: Name of collection, used to generate the next link
                          for a pagination query
        :returns: Server data in dictionary format
        """
        server_list = [func(request, server)["server"] for server in servers]
        servers_links = self._get_collection_links(request,
                                                   servers,
                                                   coll_name)
        servers_dict = dict(servers=server_list)

        if servers_links:
            servers_dict["servers_links"] = servers_links

        return servers_dict

    @staticmethod
    def _get_metadata(instance):
        # FIXME(danms): Transitional support for objects
        metadata = instance.get('metadata')
        if isinstance(instance, obj_base.NovaObject):
            return metadata or {}
        else:
            return utils.instance_meta(instance)

    @staticmethod
    def _get_vm_status(instance):
        # If the instance is deleted the vm and task states don't really matter
        if instance.get("deleted"):
            return "DELETED"
        return common.status_from_state(instance.get("vm_state"),
                                        instance.get("task_state"))

    @staticmethod
    def _get_host_id(instance):
        host = instance.get("host")
        project = str(instance.get("project_id"))
        if host:
            sha_hash = hashlib.sha224(project + host)
            return sha_hash.hexdigest()

    def _get_addresses(self, request, instance, extend_address=False):
        context = request.environ["nova.context"]
        networks = common.get_networks_for_instance(context, instance)
        return self._address_builder.index(networks,
                                           extend_address)["addresses"]

    def _get_image(self, request, instance):
        image_ref = instance["image_ref"]
        if image_ref:
            image_id = str(common.get_id_from_href(image_ref))
            bookmark = self._image_builder._get_bookmark_link(request,
                                                              image_id,
                                                              "images")
            return {
                "id": image_id,
                "links": [{
                    "rel": "bookmark",
                    "href": bookmark,
                }],
            }
        else:
            return ""

    def _get_flavor(self, request, instance):
        instance_type = instance.get_flavor()
        if not instance_type:
            LOG.warning(_LW("Instance has had its instance_type removed "
                            "from the DB"), instance=instance)
            return {}
        flavor_id = instance_type["flavorid"]
        flavor_bookmark = self._flavor_builder._get_bookmark_link(request,
                                                                  flavor_id,
                                                                  "flavors")
        return {
            "id": str(flavor_id),
            "links": [{
                "rel": "bookmark",
                "href": flavor_bookmark,
            }],
        }

    def _get_fault(self, request, instance):
        # This can result in a lazy load of the fault information
        fault = instance.fault

        if not fault:
            return None

        fault_dict = {
            "code": fault["code"],
            "created": utils.isotime(fault["created_at"]),
            "message": fault["message"],
        }

        if fault.get('details', None):
            is_admin = False
            context = request.environ["nova.context"]
            if context:
                is_admin = getattr(context, 'is_admin', False)

            if is_admin or fault['code'] != 500:
                fault_dict['details'] = fault["details"]

        return fault_dict


class ViewBuilderV21(ViewBuilder):
    """Model a server v2.1 API response as a python dictionary."""

    def __init__(self):
        """Initialize view builder."""
        super(ViewBuilderV21, self).__init__()
        self._address_builder = views_addresses.ViewBuilderV21()
        # TODO(alex_xu): In V3 API, we correct the image bookmark link to
        # use glance endpoint. We revert back it to use nova endpoint for v2.1.
        self._image_builder = views_images.ViewBuilder()

    def show(self, request, instance, extend_address=True):
        """Detailed view of a single instance."""
        server = {
            "server": {
                "id": instance["uuid"],
                "name": instance["display_name"],
                "status": self._get_vm_status(instance),
                "tenant_id": instance.get("project_id") or "",
                "user_id": instance.get("user_id") or "",
                "metadata": self._get_metadata(instance),
                "hostId": self._get_host_id(instance) or "",
                # TODO(alex_xu): '_get_image' return {} when there image_ref
                # isn't existed in V3 API, we revert it back to return "" in
                # V2.1.
                "image": self._get_image(request, instance),
                "flavor": self._get_flavor(request, instance),
                "created": utils.isotime(instance["created_at"]),
                "updated": utils.isotime(instance["updated_at"]),
                "addresses": self._get_addresses(request, instance,
                                                 extend_address),
                "links": self._get_links(request,
                                         instance["uuid"],
                                         self._collection_name),
            },
        }
        if server["server"]["status"] in self._fault_statuses:
            _inst_fault = self._get_fault(request, instance)
            if _inst_fault:
                server['server']['fault'] = _inst_fault

        if server["server"]["status"] in self._progress_statuses:
            server["server"]["progress"] = instance.get("progress", 0)

        if api_version_request.is_supported(request, min_version="2.9"):
            server["server"]["locked"] = (True if instance["locked_by"]
                                          else False)

        if api_version_request.is_supported(request, min_version="2.19"):
            server["server"]["description"] = instance.get(
                                                "display_description")

        return server
