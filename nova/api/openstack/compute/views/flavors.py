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

from nova.api.openstack import common


class ViewBuilder(common.ViewBuilder):

    _collection_name = "flavors"

    def basic(self, request, flavor):
        return {
            "flavor": {
                "id": flavor["flavorid"],
                "name": flavor["name"],
                "links": self._get_links(request,
                                         flavor["flavorid"],
                                         self._collection_name),
            },
        }

    def show(self, request, flavor):
        flavor_dict = {
            "flavor": {
                "id": flavor["flavorid"],
                "name": flavor["name"],
                "ram": flavor["memory_mb"],
                "disk": flavor["root_gb"],
                "vcpus": flavor.get("vcpus") or "",
                "links": self._get_links(request,
                                         flavor["flavorid"],
                                         self._collection_name),
            },
        }

        return flavor_dict

    def index(self, request, flavors):
        """Return the 'index' view of flavors."""
        coll_name = self._collection_name
        return self._list_view(self.basic, request, flavors, coll_name)

    def detail(self, request, flavors):
        """Return the 'detail' view of flavors."""
        coll_name = self._collection_name + '/detail'
        return self._list_view(self.show, request, flavors, coll_name)

    def _list_view(self, func, request, flavors, coll_name):
        """Provide a view for a list of flavors.

        :param func: Function used to format the flavor data
        :param request: API request
        :param flavors: List of flavors in dictionary format
        :param coll_name: Name of collection, used to generate the next link
                          for a pagination query

        :returns: Flavor reply data in dictionary format
        """
        flavor_list = [func(request, flavor)["flavor"] for flavor in flavors]
        flavors_links = self._get_collection_links(request,
                                                   flavors,
                                                   coll_name,
                                                   "flavorid")
        flavors_dict = dict(flavors=flavor_list)

        if flavors_links:
            flavors_dict["flavors_links"] = flavors_links

        return flavors_dict


class ViewBuilderV21(ViewBuilder):
    def show(self, request, flavor):
        flavor_dict = super(ViewBuilderV21, self).show(request, flavor)
        flavor_dict['flavor'].update({
            "swap": flavor["swap"] or "",
            "OS-FLV-EXT-DATA:ephemeral": flavor["ephemeral_gb"],
            "OS-FLV-DISABLED:disabled": flavor["disabled"],
            "vcpus": flavor["vcpus"],
        })
        return flavor_dict
