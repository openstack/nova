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
from nova.policies import flavor_access as fa_policies
from nova.policies import flavor_rxtx as fr_policies

FLAVOR_DESCRIPTION_MICROVERSION = '2.55'


class ViewBuilder(common.ViewBuilder):

    _collection_name = "flavors"

    def basic(self, request, flavor, include_description=False,
              update_is_public=None, update_rxtx_factor=None):
        # update_is_public & update_rxtx_factor are placeholder param
        # which are not used in this method as basic() method is used by
        # index() (GET /flavors) which does not return those keys in response.
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

    def show(self, request, flavor, include_description=False,
             update_is_public=None, update_rxtx_factor=None):
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

        # TODO(gmann): 'update_is_public' & 'update_rxtx_factor' are policies
        # checks. Once os-flavor-access & os-flavor-rxtx policies are
        # removed, 'os-flavor-access:is_public' and 'rxtx_factor' need to be
        # added in response without any check.

        # Evaluate the policies when using show method directly.
        context = request.environ['nova.context']
        if update_is_public is None:
            update_is_public = context.can(fa_policies.BASE_POLICY_NAME,
                                           fatal=False)
        if update_rxtx_factor is None:
            update_rxtx_factor = context.can(fr_policies.BASE_POLICY_NAME,
                                             fatal=False)
        if update_is_public:
            flavor_dict['flavor'].update({
                "os-flavor-access:is_public": flavor['is_public']})
        if update_rxtx_factor:
            flavor_dict['flavor'].update(
                {"rxtx_factor": flavor['rxtx_factor'] or ""})

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
        context = request.environ['nova.context']
        update_is_public = context.can(fa_policies.BASE_POLICY_NAME,
                                       fatal=False)
        update_rxtx_factor = context.can(fr_policies.BASE_POLICY_NAME,
                                         fatal=False)
        return self._list_view(self.show, request, flavors, coll_name,
                               include_description=include_description,
                               update_is_public=update_is_public,
                               update_rxtx_factor=update_rxtx_factor)

    def _list_view(self, func, request, flavors, coll_name,
                   include_description=False, update_is_public=None,
                   update_rxtx_factor=None):
        """Provide a view for a list of flavors.

        :param func: Function used to format the flavor data
        :param request: API request
        :param flavors: List of flavors in dictionary format
        :param coll_name: Name of collection, used to generate the next link
                          for a pagination query
        :param include_description: If the flavor.description should be
                                    included in the response dict.
        :param update_is_public: If the flavor.is_public field should be
                                 included in the response dict.
        :param update_rxtx_factor: If the flavor.rxtx_factor field should be
                                   included in the response dict.

        :returns: Flavor reply data in dictionary format
        """
        flavor_list = [func(request, flavor, include_description,
                            update_is_public, update_rxtx_factor)["flavor"]
                       for flavor in flavors]
        flavors_links = self._get_collection_links(request,
                                                   flavors,
                                                   coll_name,
                                                   "flavorid")
        flavors_dict = dict(flavors=flavor_list)

        if flavors_links:
            flavors_dict["flavors_links"] = flavors_links

        return flavors_dict
