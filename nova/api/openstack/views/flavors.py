# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010-2011 OpenStack LLC.
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


def get_view_builder(req):
    '''
    A factory method that returns the correct builder based on the version of
    the api requested.
    '''
    version = common.get_api_version(req)
    base_url = req.application_url
    if version == '1.1':
        return ViewBuilder_1_1(base_url)
    else:
        return ViewBuilder_1_0()


class ViewBuilder(object):
    def __init__(self):
        pass

    def build(self, flavor_obj, is_detail=False):
        if is_detail:
            flavor = self._build_detail(flavor_obj)
        else:
            flavor = self._build_simple(flavor_obj)

        full_flavor = self._build_extra(flavor)

        return full_flavor

    def _build_simple(self, flavor_obj):
        return {
            "id": flavor_obj["flavorid"],
            "name": flavor_obj["name"],
        }

    def _build_detail(self, flavor_obj):
        simple = self._build_simple(flavor_obj)

        detail = {
            "ram": flavor_obj["memory_mb"],
            "disk": flavor_obj["local_gb"],
        }

        detail.update(simple)

        return detail 
    
    def _build_extra(self, flavor_obj):
        return flavor_obj


class ViewBuilder_1_1(ViewBuilder):
    def __init__(self, base_url):
        self.base_url = base_url

    def _build_extra(self, flavor_obj):
        flavor_obj["links"] = self._build_links(flavor_obj)
        return flavor_obj

    def _build_links(self, flavor_obj):
        href = self.generate_href(flavor_obj["id"])
        links = [
            {
                "rel": "self",
                "href": href,
            },
            {
                "rel": "bookmark",
                "type": "application/json",
                "href": href,
            },
            {
                "rel": "bookmark",
                "type": "application/xml",
                "href": href,
            },
        ]
        return links

    def generate_href(self, flavor_id):
        return "%s/flavors/%s" % (self.base_url, flavor_id)


class ViewBuilder_1_0(ViewBuilder):
    pass
