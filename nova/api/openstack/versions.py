# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

import webob
import webob.dec
from xml.dom import minidom

import nova.api.openstack.views.versions
from nova.api.openstack import wsgi


class Versions(wsgi.Resource):
    def __init__(self):
        metadata = {
            "attributes": {
                "version": ["status", "id"],
                "link": ["rel", "href"],
            }
        }

        body_serializers = {
            'application/xml': VersionsXMLSerializer(metadata=metadata),
        }
        serializer = wsgi.ResponseSerializer(body_serializers)

        wsgi.Resource.__init__(self, None, serializer=serializer)

    def dispatch(self, request, *args):
        """Respond to a request for all OpenStack API versions."""
        version_objs = [
            {
                "id": "v1.1",
                "status": "CURRENT",
            },
            {
                "id": "v1.0",
                "status": "DEPRECATED",
            },
        ]

        builder = nova.api.openstack.views.versions.get_view_builder(request)
        versions = [builder.build(version) for version in version_objs]
        return dict(versions=versions)

class VersionsXMLSerializer(wsgi.XMLDictSerializer):
    def __init__(self, metadata=None, xmlns=None):
        super(VersionsXMLSerializer, self).__init__(metadata, xmlns)

    def _versions_to_xml(self, versions):
        root = self.xml_doc.createElement('versions')

        for version in versions:
            root.appendChild(self._create_version_node(version))

        return root

    def _create_version_node(self, version):
        version_node = self.xml_doc.createElement('version')
        version_node.setAttribute('id', version['id'])
        version_node.setAttribute('status', version['status'])
        #TODO(wwolf) need 'updated' attribute too

        for link in version['links']:
            link_node = self.xml_doc.createElement('atom:link')
            link_node.setAttribute('rel', link['rel'])
            link_node.setAttribute('href', link['href'])
            version_node.appendChild(link_node)

        return version_node


    def default(self, data):
        self.xml_doc = minidom.Document()
        node = self._versions_to_xml(data['versions'])

        return self.to_xml_string(node)
