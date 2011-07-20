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


ATOM_XMLNS = "http://www.w3.org/2005/Atom"


class Versions(wsgi.Resource):

    def __init__(self):
        metadata = {
            "attributes": {
                "version": ["status", "id"],
                "link": ["rel", "href"],
            }
        }

        body_serializers = {
            'application/atom+xml': VersionsAtomSerializer(metadata=metadata),
            'application/xml': VersionsXMLSerializer(metadata=metadata),
        }
        serializer = wsgi.ResponseSerializer(body_serializers)

        supported_content_types = ('application/json', 
                                   'application/xml', 
                                   'application/atom+xml')
        deserializer = wsgi.RequestDeserializer(
            supported_content_types=supported_content_types)

        wsgi.Resource.__init__(self, None, serializer=serializer,
                               deserializer=deserializer)

    def dispatch(self, request, *args):
        """Respond to a request for all OpenStack API versions."""
        version_objs = [
            {
                "id": "v1.1",
                "status": "CURRENT",
                #TODO(wwolf) get correct value for these
                "updated": "2011-7-18T11:30:00Z",
            },
            {
                "id": "v1.0",
                "status": "DEPRECATED",
                #TODO(wwolf) get correct value for these
                "updated": "2010-10-09T11:30:00Z",
            },
        ]

        builder = nova.api.openstack.views.versions.get_view_builder(request)
        versions = [builder.build(version) for version in version_objs]
        return dict(versions=versions)

class VersionsXMLSerializer(wsgi.XMLDictSerializer):
    def _versions_to_xml(self, versions):
        root = self._xml_doc.createElement('versions')

        for version in versions:
            root.appendChild(self._create_version_node(version))

        return root

    def _create_version_node(self, version):
        version_node = self._xml_doc.createElement('version')
        version_node.setAttribute('id', version['id'])
        version_node.setAttribute('status', version['status'])
        version_node.setAttribute('updated', version['updated'])

        for link in version['links']:
            link_node = self._xml_doc.createElement('atom:link')
            link_node.setAttribute('rel', link['rel'])
            link_node.setAttribute('href', link['href'])
            version_node.appendChild(link_node)

        return version_node


    def default(self, data):
        self._xml_doc = minidom.Document()
        node = self._versions_to_xml(data['versions'])

        return self.to_xml_string(node)

class VersionsAtomSerializer(wsgi.XMLDictSerializer):
    def __init__(self, metadata=None, xmlns=None):
        if not xmlns:
            self.xmlns = ATOM_XMLNS
        else:
            self.xmlns = xmlns

    def _create_text_elem(self, name, text, type=None):
        elem = self._xml_doc.createElement(name)
        if type:
            elem.setAttribute('type', type)
        elem_text = self._xml_doc.createTextNode(text)
        elem.appendChild(elem_text)
        return elem

    def _create_meta(self, root):
        title = self._create_text_elem('title', 'Available API Versions',
                                       type='text')
        #TODO(wwolf): what should updated be?
        updated = self._create_text_elem('updated', '2010-12-12T18:30:02.25Z')
        #TODO(wwolf): get URI
        id = self._create_text_elem('id', '')
        #TODO(wwolf): get link info
        link = self._xml_doc.createElement('link')
        link.setAttribute('rel', 'rel')
        link.setAttribute('href', 'href')

        author = self._xml_doc.createElement('author')
        author_name = self._create_text_elem('name', 'Rackspace')
        author_uri = self._create_text_elem('uri', 'http://www.rackspace.com')
        author.appendChild(author_name)
        author.appendChild(author_uri)

        root.appendChild(title)
        root.appendChild(updated)
        root.appendChild(id)
        root.appendChild(link)
        root.appendChild(author)

    def _create_version_entries(self, root, versions):
        for version in versions:
            entry = self._xml_doc.createElement('entry')
            #TODO(wwolf) GET URI
            id = self._create_text_elem('id', 'URI')
            title = self._create_text_elem('title', 
                                           'Version %s' % version['id'],
                                           type='text')
            updated = self._create_text_elem('updated', version['updated'])
            #TODO(wwolf): get link info
            link = self._xml_doc.createElement('link')
            link.setAttribute('rel', 'rel')
            link.setAttribute('href', 'href')
            content = self._create_text_elem('content', 
                'Version %s %s (%s)' % 
                    (version['id'], 
                     version['status'],
                     version['updated']))

            entry.appendChild(id)
            entry.appendChild(title)
            entry.appendChild(updated)
            entry.appendChild(link)
            entry.appendChild(content)
            root.appendChild(entry)

    def default(self, data):
        self._xml_doc = minidom.Document()
        node = self._xml_doc.createElementNS(self.xmlns, 'feed')
        self._create_meta(node)
        self._create_version_entries(node, data['versions'])

        return self.to_xml_string(node)
