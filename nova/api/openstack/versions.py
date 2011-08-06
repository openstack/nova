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

from datetime import datetime
import webob
import webob.dec
from xml.dom import minidom

import nova.api.openstack.views.versions
from nova.api.openstack import wsgi


VERSIONS = {
    "v1.0": {
        "id": "v1.0",
        "status": "DEPRECATED",
        "updated": "2011-01-21T11:33:21Z",
        "links": [
            {
                "rel": "describedby",
                "type": "application/pdf",
                "href": "http://docs.rackspacecloud.com/"
                        "servers/api/v1.0/cs-devguide-20110125.pdf",
            },
            {
                "rel": "describedby",
                "type": "application/vnd.sun.wadl+xml",
                "href": "http://docs.rackspacecloud.com/"
                        "servers/api/v1.0/application.wadl",
            },
        ],
        "media-types": [
            {
                "base": "application/xml",
                "type": "application/vnd.openstack.compute-v1.0+xml",
            },
            {
                "base": "application/json",
                "type": "application/vnd.openstack.compute-v1.0+json",
            }
        ],
    },
    "v1.1": {
        "id": "v1.1",
        "status": "CURRENT",
        "updated": "2011-01-21T11:33:21Z",
        "links": [
            {
                "rel": "describedby",
                "type": "application/pdf",
                "href": "http://docs.rackspacecloud.com/"
                        "servers/api/v1.1/cs-devguide-20110125.pdf",
            },
            {
                "rel": "describedby",
                "type": "application/vnd.sun.wadl+xml",
                "href": "http://docs.rackspacecloud.com/"
                        "servers/api/v1.1/application.wadl",
            },
        ],
        "media-types": [
            {
                "base": "application/xml",
                "type": "application/vnd.openstack.compute-v1.1+xml",
            },
            {
                "base": "application/json",
                "type": "application/vnd.openstack.compute-v1.1+json",
            }
        ],
    },
}


class Versions(wsgi.Resource):
    def __init__(self):
        metadata = {
            "attributes": {
                "version": ["status", "id"],
                "link": ["rel", "href"],
            }
        }

        headers_serializer = VersionsHeadersSerializer()

        body_serializers = {
            'application/atom+xml': VersionsAtomSerializer(metadata=metadata),
            'application/xml': VersionsXMLSerializer(metadata=metadata),
        }
        serializer = wsgi.ResponseSerializer(
            body_serializers=body_serializers,
            headers_serializer=headers_serializer)

        supported_content_types = ('application/json',
                                   'application/xml',
                                   'application/atom+xml')
        deserializer = VersionsRequestDeserializer(
            supported_content_types=supported_content_types)

        wsgi.Resource.__init__(self, None, serializer=serializer,
                               deserializer=deserializer)

    def dispatch(self, request, *args):
        """Respond to a request for all OpenStack API versions."""
        builder = nova.api.openstack.views.versions.get_view_builder(request)
        if request.path == '/':
            # List Versions
            return builder.build_versions(VERSIONS)
        else:
            # Versions Multiple Choice
            return builder.build_choices(VERSIONS, request)


class VersionV10(object):
    def show(self, req):
        builder = nova.api.openstack.views.versions.get_view_builder(req)
        return builder.build_version(VERSIONS['v1.0'])


class VersionV11(object):
    def show(self, req):
        builder = nova.api.openstack.views.versions.get_view_builder(req)
        return builder.build_version(VERSIONS['v1.1'])


class VersionsRequestDeserializer(wsgi.RequestDeserializer):
    def get_expected_content_type(self, request):
        supported_content_types = list(self.supported_content_types)
        if request.path != '/':
            # Remove atom+xml accept type for 300 responses
            if 'application/atom+xml' in supported_content_types:
                supported_content_types.remove('application/atom+xml')

        return request.best_match_content_type(supported_content_types)

    def get_action_args(self, request_environment):
        """Parse dictionary created by routes library."""
        args = {}
        if request_environment['PATH_INFO'] == '/':
            args['action'] = 'index'
        else:
            args['action'] = 'multi'

        return args


class VersionsXMLSerializer(wsgi.XMLDictSerializer):
    #TODO(wwolf): this is temporary until we get rid of toprettyxml
    # in the base class (XMLDictSerializer), which I plan to do in
    # another branch
    def to_xml_string(self, node, has_atom=False):
        self._add_xmlns(node, has_atom)
        return node.toxml(encoding='UTF-8')

    def _versions_to_xml(self, versions, name="versions", xmlns=None):
        root = self._xml_doc.createElement(name)
        root.setAttribute("xmlns", wsgi.XMLNS_V11)
        root.setAttribute("xmlns:atom", wsgi.XMLNS_ATOM)

        for version in versions:
            root.appendChild(self._create_version_node(version))

        return root

    def _create_media_types(self, media_types):
        base = self._xml_doc.createElement('media-types')
        for type in media_types:
            node = self._xml_doc.createElement('media-type')
            node.setAttribute('base', type['base'])
            node.setAttribute('type', type['type'])
            base.appendChild(node)

        return base

    def _create_version_node(self, version, create_ns=False):
        version_node = self._xml_doc.createElement('version')
        if create_ns:
            xmlns = wsgi.XMLNS_V11
            xmlns_atom = wsgi.XMLNS_ATOM
            version_node.setAttribute('xmlns', xmlns)
            version_node.setAttribute('xmlns:atom', xmlns_atom)

        version_node.setAttribute('id', version['id'])
        version_node.setAttribute('status', version['status'])
        if 'updated' in version:
            version_node.setAttribute('updated', version['updated'])

        if 'media-types' in version:
            media_types = self._create_media_types(version['media-types'])
            version_node.appendChild(media_types)

        link_nodes = self._create_link_nodes(self._xml_doc, version['links'])
        for link in link_nodes:
            version_node.appendChild(link)

        return version_node

    def index(self, data):
        self._xml_doc = minidom.Document()
        node = self._versions_to_xml(data['versions'])

        return self.to_xml_string(node)

    def show(self, data):
        self._xml_doc = minidom.Document()
        node = self._create_version_node(data['version'], True)

        return self.to_xml_string(node)

    def multi(self, data):
        self._xml_doc = minidom.Document()
        node = self._versions_to_xml(data['choices'], 'choices',
                         xmlns=wsgi.XMLNS_V11)

        return self.to_xml_string(node)


class VersionsAtomSerializer(wsgi.XMLDictSerializer):
    #TODO(wwolf): this is temporary until we get rid of toprettyxml
    # in the base class (XMLDictSerializer), which I plan to do in
    # another branch
    def to_xml_string(self, node, has_atom=False):
        self._add_xmlns(node, has_atom)
        return node.toxml(encoding='UTF-8')

    def __init__(self, metadata=None, xmlns=None):
        self.metadata = metadata or {}
        if not xmlns:
            self.xmlns = wsgi.XMLNS_ATOM
        else:
            self.xmlns = xmlns

    def _create_text_elem(self, name, text, type=None):
        elem = self._xml_doc.createElement(name)
        if type:
            elem.setAttribute('type', type)
        elem_text = self._xml_doc.createTextNode(text)
        elem.appendChild(elem_text)
        return elem

    def _get_most_recent_update(self, versions):
        recent = None
        for version in versions:
            updated = datetime.strptime(version['updated'],
                                        '%Y-%m-%dT%H:%M:%SZ')
            if not recent:
                recent = updated
            elif updated > recent:
                recent = updated

        return recent.strftime('%Y-%m-%dT%H:%M:%SZ')

    def _get_base_url(self, link_href):
        # Make sure no trailing /
        link_href = link_href.rstrip('/')
        return link_href.rsplit('/', 1)[0] + '/'

    def _create_detail_meta(self, root, version):
        title = self._create_text_elem('title', "About This Version",
                                       type='text')

        updated = self._create_text_elem('updated', version['updated'])

        uri = version['links'][0]['href']
        id = self._create_text_elem('id', uri)

        link = self._xml_doc.createElement('link')
        link.setAttribute('rel', 'self')
        link.setAttribute('href', uri)

        author = self._xml_doc.createElement('author')
        author_name = self._create_text_elem('name', 'Rackspace')
        author_uri = self._create_text_elem('uri', 'http://www.rackspace.com/')
        author.appendChild(author_name)
        author.appendChild(author_uri)

        root.appendChild(title)
        root.appendChild(updated)
        root.appendChild(id)
        root.appendChild(author)
        root.appendChild(link)

    def _create_list_meta(self, root, versions):
        title = self._create_text_elem('title', "Available API Versions",
                                       type='text')
        # Set this updated to the most recently updated version
        recent = self._get_most_recent_update(versions)
        updated = self._create_text_elem('updated', recent)

        base_url = self._get_base_url(versions[0]['links'][0]['href'])
        id = self._create_text_elem('id', base_url)

        link = self._xml_doc.createElement('link')
        link.setAttribute('rel', 'self')
        link.setAttribute('href', base_url)

        author = self._xml_doc.createElement('author')
        author_name = self._create_text_elem('name', 'Rackspace')
        author_uri = self._create_text_elem('uri', 'http://www.rackspace.com/')
        author.appendChild(author_name)
        author.appendChild(author_uri)

        root.appendChild(title)
        root.appendChild(updated)
        root.appendChild(id)
        root.appendChild(author)
        root.appendChild(link)

    def _create_version_entries(self, root, versions):
        for version in versions:
            entry = self._xml_doc.createElement('entry')

            id = self._create_text_elem('id', version['links'][0]['href'])
            title = self._create_text_elem('title',
                                           'Version %s' % version['id'],
                                           type='text')
            updated = self._create_text_elem('updated', version['updated'])

            entry.appendChild(id)
            entry.appendChild(title)
            entry.appendChild(updated)

            for link in version['links']:
                link_node = self._xml_doc.createElement('link')
                link_node.setAttribute('rel', link['rel'])
                link_node.setAttribute('href', link['href'])
                if 'type' in link:
                    link_node.setAttribute('type', link['type'])

                entry.appendChild(link_node)

            content = self._create_text_elem('content',
                'Version %s %s (%s)' %
                    (version['id'],
                     version['status'],
                     version['updated']),
                type='text')

            entry.appendChild(content)
            root.appendChild(entry)

    def index(self, data):
        self._xml_doc = minidom.Document()
        node = self._xml_doc.createElementNS(self.xmlns, 'feed')
        self._create_list_meta(node, data['versions'])
        self._create_version_entries(node, data['versions'])

        return self.to_xml_string(node)

    def show(self, data):
        self._xml_doc = minidom.Document()
        node = self._xml_doc.createElementNS(self.xmlns, 'feed')
        self._create_detail_meta(node, data['version'])
        self._create_version_entries(node, [data['version']])

        return self.to_xml_string(node)


class VersionsHeadersSerializer(wsgi.ResponseHeadersSerializer):
    def multi(self, response, data):
        response.status_int = 300


def create_resource(version='1.0'):
    controller = {
        '1.0': VersionV10,
        '1.1': VersionV11,
    }[version]()

    body_serializers = {
        'application/xml': VersionsXMLSerializer(),
        'application/atom+xml': VersionsAtomSerializer(),
    }
    serializer = wsgi.ResponseSerializer(body_serializers)

    supported_content_types = ('application/json',
                               'application/xml',
                               'application/atom+xml')
    deserializer = wsgi.RequestDeserializer(
        supported_content_types=supported_content_types)

    return wsgi.Resource(controller, serializer=serializer,
                         deserializer=deserializer)
