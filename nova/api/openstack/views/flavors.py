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

import os.path


from nova.api.openstack import common


class ViewBuilder(object):

    def build(self, flavor_obj, is_detail=False):
        """Generic method used to generate a flavor entity."""
        if is_detail:
            flavor = self._build_detail(flavor_obj)
        else:
            flavor = self._build_simple(flavor_obj)

        self._build_extra(flavor)

        return flavor

    def _build_simple(self, flavor_obj):
        """Build a minimal representation of a flavor."""
        return {
            "id": flavor_obj["flavorid"],
            "name": flavor_obj["name"],
        }

    def _build_detail(self, flavor_obj):
        """Build a more complete representation of a flavor."""
        simple = self._build_simple(flavor_obj)

        detail = {
            "ram": flavor_obj["memory_mb"],
            "disk": flavor_obj["local_gb"],
        }

        for key in ("vcpus", "swap", "rxtx_quota", "rxtx_cap"):
            detail[key] = flavor_obj.get(key, "")

        detail.update(simple)

        return detail

    def _build_extra(self, flavor_obj):
        """Hook for version-specific changes to newly created flavor object."""
        pass


class ViewBuilderV11(ViewBuilder):
    """Openstack API v1.1 flavors view builder."""

    def __init__(self, base_url, project_id=""):
        """
        :param base_url: url of the root wsgi application
        """
        self.base_url = base_url
        self.project_id = project_id

    def _build_extra(self, flavor_obj):
        flavor_obj["links"] = self._build_links(flavor_obj)

    def _build_links(self, flavor_obj):
        """Generate a container of links that refer to the provided flavor."""
        href = self.generate_href(flavor_obj["id"])
        bookmark = self.generate_bookmark(flavor_obj["id"])

        links = [
            {
                "rel": "self",
                "href": href,
            },
            {
                "rel": "bookmark",
                "href": bookmark,
            },
        ]

        return links

    def generate_href(self, flavor_id):
        """Create an url that refers to a specific flavor id."""
        return os.path.join(self.base_url, self.project_id,
                            "flavors", str(flavor_id))

    def generate_bookmark(self, flavor_id):
        """Create an url that refers to a specific flavor id."""
        return os.path.join(common.remove_version_from_href(self.base_url),
            self.project_id, "flavors", str(flavor_id))
