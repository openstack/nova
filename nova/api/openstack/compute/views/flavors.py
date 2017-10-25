# Copyright 2010-2011 OpenStack Foundation
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

from nova.api.openstack import api_version_request
from nova.api.openstack import common

FLAVOR_DESCRIPTION_MICROVERSION = '2.55'


class ViewBuilder(common.ViewBuilder):

    _collection_name = "flavors"

    def basic(self, request, flavor, include_description=False):
        flavor_dict = {
            "flavor": {
                "id": flavor["flavorid"],
                "name": flavor["name"],
                "links": self._get_links(request,
                                         flavor["flavorid"],
                                         self._collection_name),
            },
        }

        if include_description:
            flavor_dict['flavor']['description'] = flavor.description

        return flavor_dict

    def show(self, request, flavor, include_description=False):
        flavor_dict = {
            "flavor": {
                "id": flavor["flavorid"],
                "name": flavor["name"],
                "ram": flavor["memory_mb"],
                "disk": flavor["root_gb"],
                "swap": flavor["swap"] or "",
                "OS-FLV-EXT-DATA:ephemeral": flavor["ephemeral_gb"],
                "OS-FLV-DISABLED:disabled": flavor["disabled"],
                "vcpus": flavor["vcpus"],
                "links": self._get_links(request,
                                         flavor["flavorid"],
                                         self._collection_name),
            },
        }

        if include_description:
            flavor_dict['flavor']['description'] = flavor.description

        return flavor_dict

    def index(self, request, flavors):
        """Return the 'index' view of flavors."""
        coll_name = self._collection_name
        include_description = api_version_request.is_supported(
            request, FLAVOR_DESCRIPTION_MICROVERSION)
        return self._list_view(self.basic, request, flavors, coll_name,
                               include_description=include_description)

    def detail(self, request, flavors):
        """Return the 'detail' view of flavors."""
        coll_name = self._collection_name + '/detail'
        include_description = api_version_request.is_supported(
            request, FLAVOR_DESCRIPTION_MICROVERSION)
        return self._list_view(self.show, request, flavors, coll_name,
                               include_description=include_description)

    def _list_view(self, func, request, flavors, coll_name,
                   include_description=False):
        """Provide a view for a list of flavors.

        :param func: Function used to format the flavor data
        :param request: API request
        :param flavors: List of flavors in dictionary format
        :param coll_name: Name of collection, used to generate the next link
                          for a pagination query
        :param include_description: If the flavor.description should be
                                    included in the response dict.

        :returns: Flavor reply data in dictionary format
        """
        flavor_list = [func(request, flavor, include_description)["flavor"]
                       for flavor in flavors]
        flavors_links = self._get_collection_links(request,
                                                   flavors,
                                                   coll_name,
                                                   "flavorid")
        flavors_dict = dict(flavors=flavor_list)

        if flavors_links:
            flavors_dict["flavors_links"] = flavors_links

        return flavors_dict
