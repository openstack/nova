# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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


from nova.api.openstack.compute import versions
from nova.api.openstack.volume.views import versions as views_versions
from nova.api.openstack import wsgi


VERSIONS = {
    "v1": {
        "id": "v1",
        "status": "CURRENT",
        "updated": "2012-01-04T11:33:21Z",
        "links": [
            {
                "rel": "describedby",
                "type": "application/pdf",
                "href": "http://jorgew.github.com/block-storage-api/"
                        "content/os-block-storage-1.0.pdf",
            },
            {
                "rel": "describedby",
                "type": "application/vnd.sun.wadl+xml",
                #(anthony) FIXME
                "href": "http://docs.rackspacecloud.com/"
                        "servers/api/v1.1/application.wadl",
            },
        ],
        "media-types": [
            {
                "base": "application/xml",
                "type": "application/vnd.openstack.volume+xml;version=1",
            },
            {
                "base": "application/json",
                "type": "application/vnd.openstack.volume+json;version=1",
            }
        ],
    }
}


class Versions(versions.Versions):
    def dispatch(self, request, *args):
        """Respond to a request for all OpenStack API versions."""
        builder = views_versions.get_view_builder(request)
        if request.path == '/':
            # List Versions
            return builder.build_versions(VERSIONS)
        else:
            # Versions Multiple Choice
            return builder.build_choices(VERSIONS, request)


class VolumeVersionV1(object):
    @wsgi.serializers(xml=versions.VersionTemplate,
                      atom=versions.VersionAtomSerializer)
    def show(self, req):
        builder = views_versions.get_view_builder(req)
        return builder.build_version(VERSIONS['v2.0'])


def create_resource():
    return wsgi.Resource(VolumeVersionV1())
