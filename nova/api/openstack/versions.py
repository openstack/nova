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
from lxml import etree
import webob
import webob.dec

import nova.api.openstack.views.versions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil


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

    def _populate_version(self, version_node, version):
        version_node.set('id', version['id'])
        version_node.set('status', version['status'])
        if 'updated' in version:
            version_node.set('updated', version['updated'])
        if 'media-types' in version:
            media_types = etree.SubElement(version_node, 'media-types')
            for mtype in version['media-types']:
                elem = etree.SubElement(media_types, 'media-type')
                elem.set('base', mtype['base'])
                elem.set('type', mtype['type'])
        for link in version.get('links', []):
            elem = etree.SubElement(version_node,
                                    '{%s}link' % xmlutil.XMLNS_ATOM)
            elem.set('rel', link['rel'])
            elem.set('href', link['href'])
            if 'type' in link:
                elem.set('type', link['type'])

    NSMAP = {None: xmlutil.XMLNS_V11, 'atom': xmlutil.XMLNS_ATOM}

    def index(self, data):
        root = etree.Element('versions', nsmap=self.NSMAP)
        for version in data['versions']:
            version_elem = etree.SubElement(root, 'version')
            self._populate_version(version_elem, version)
        return self._to_xml(root)

    def show(self, data):
        root = etree.Element('version', nsmap=self.NSMAP)
        self._populate_version(root, data['version'])
        return self._to_xml(root)

    def multi(self, data):
        root = etree.Element('choices', nsmap=self.NSMAP)
        for version in data['choices']:
            version_elem = etree.SubElement(root, 'version')
            self._populate_version(version_elem, version)
        return self._to_xml(root)


class VersionsAtomSerializer(wsgi.XMLDictSerializer):

    NSMAP = {None: xmlutil.XMLNS_ATOM}

    def __init__(self, metadata=None, xmlns=None):
        self.metadata = metadata or {}
        if not xmlns:
            self.xmlns = wsgi.XMLNS_ATOM
        else:
            self.xmlns = xmlns

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

    def _create_feed(self, versions, feed_title, feed_id):
        feed = etree.Element('feed', nsmap=self.NSMAP)
        title = etree.SubElement(feed, 'title')
        title.set('type', 'text')
        title.text = feed_title

        # Set this updated to the most recently updated version
        recent = self._get_most_recent_update(versions)
        etree.SubElement(feed, 'updated').text = recent

        etree.SubElement(feed, 'id').text = feed_id

        link = etree.SubElement(feed, 'link')
        link.set('rel', 'self')
        link.set('href', feed_id)

        author = etree.SubElement(feed, 'author')
        etree.SubElement(author, 'name').text = 'Rackspace'
        etree.SubElement(author, 'uri').text = 'http://www.rackspace.com/'

        for version in versions:
            feed.append(self._create_version_entry(version))

        return feed

    def _create_version_entry(self, version):
        entry = etree.Element('entry')
        etree.SubElement(entry, 'id').text = version['links'][0]['href']
        title = etree.SubElement(entry, 'title')
        title.set('type', 'text')
        title.text = 'Version %s' % version['id']
        etree.SubElement(entry, 'updated').text = version['updated']

        for link in version['links']:
            link_elem = etree.SubElement(entry, 'link')
            link_elem.set('rel', link['rel'])
            link_elem.set('href', link['href'])
            if 'type' in link:
                link_elem.set('type', link['type'])

        content = etree.SubElement(entry, 'content')
        content.set('type', 'text')
        content.text = 'Version %s %s (%s)' % (version['id'],
                                               version['status'],
                                               version['updated'])
        return entry

    def index(self, data):
        versions = data['versions']
        feed_id = self._get_base_url(versions[0]['links'][0]['href'])
        feed = self._create_feed(versions, 'Available API Versions', feed_id)
        return self._to_xml(feed)

    def show(self, data):
        version = data['version']
        feed_id = version['links'][0]['href']
        feed = self._create_feed([version], 'About This Version', feed_id)
        return self._to_xml(feed)


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
