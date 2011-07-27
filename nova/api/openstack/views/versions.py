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

import os


def get_view_builder(req):
    base_url = req.application_url
    return ViewBuilder(base_url)


class ViewBuilder(object):

    def __init__(self, base_url):
        """
        :param base_url: url of the root wsgi application
        """
        self.base_url = base_url

    def build_choices(self, VERSIONS, request):
        version_objs = []
        for version in VERSIONS:
            version = VERSIONS[version]['version']
            version_objs.append({
                "id": version['id'],
                "status": version['status'],
                "links": [
                    {
                        "rel": "self",
                        "href": self._build_versioned_link(request,
                                                           version['id'])
                    }
                ],
                "media-types": version['media-types']
            })

        return dict(choices=version_objs)

    def build(self, VERSIONS):
        version_objs = []
        for version in VERSIONS:
            version = VERSIONS[version]['version']
            version_objs.append({
                "id": version['id'],
                "status": version['status'],
                "updated": version['updated'],
                "links": self._build_links(version),
            })

        return dict(versions=version_objs)

    def _build_versioned_link(self, req, version):
        return '%s://%s/%s%s' % (req.scheme, req.host, version, req.path)

    def _build_links(self, version_data):
        """Generate a container of links that refer to the provided version."""
        href = self.generate_href(version_data["id"])

        links = [
            {
                "rel": "self",
                "href": href,
            },
        ]

        return links

    def generate_href(self, version_number):
        """Create an url that refers to a specific version_number."""
        return os.path.join(self.base_url, version_number) + '/'
