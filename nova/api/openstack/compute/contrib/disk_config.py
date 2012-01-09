# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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
#    under the License

"""Disk Config extension."""

from xml.dom import minidom

from webob import exc

from nova.api.openstack import extensions
from nova.api.openstack import xmlutil
from nova import compute
from nova import db
from nova import log as logging
from nova import utils

LOG = logging.getLogger('nova.api.openstack.contrib.disk_config')

ALIAS = 'RAX-DCF'
XMLNS_DCF = "http://docs.rackspacecloud.com/servers/api/ext/diskConfig/v1.0"


class ServerDiskConfigTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('server')
        root.set('{%s}diskConfig' % XMLNS_DCF, '%s:diskConfig' % ALIAS)
        return xmlutil.SlaveTemplate(root, 1, nsmap={ALIAS: XMLNS_DCF})


class ServersDiskConfigTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('servers')
        elem = xmlutil.SubTemplateElement(root, 'server', selector='servers')
        elem.set('{%s}diskConfig' % XMLNS_DCF, '%s:diskConfig' % ALIAS)
        return xmlutil.SlaveTemplate(root, 1, nsmap={ALIAS: XMLNS_DCF})


class ImageDiskConfigTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('image')
        root.set('{%s}diskConfig' % XMLNS_DCF, '%s:diskConfig' % ALIAS)
        return xmlutil.SlaveTemplate(root, 1, nsmap={ALIAS: XMLNS_DCF})


class ImagesDiskConfigTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('images')
        elem = xmlutil.SubTemplateElement(root, 'image', selector='images')
        elem.set('{%s}diskConfig' % XMLNS_DCF, '%s:diskConfig' % ALIAS)
        return xmlutil.SlaveTemplate(root, 1, nsmap={ALIAS: XMLNS_DCF})


def disk_config_to_api(value):
    return 'AUTO' if value else 'MANUAL'


def disk_config_from_api(value):
    if value == 'AUTO':
        return True
    elif value == 'MANUAL':
        return False
    else:
        msg = _("RAX-DCF:diskConfig must be either 'MANUAL' or 'AUTO'.")
        raise exc.HTTPBadRequest(explanation=msg)


class Disk_config(extensions.ExtensionDescriptor):
    """Disk Management Extension"""

    name = "DiskConfig"
    alias = ALIAS
    namespace = XMLNS_DCF
    updated = "2011-09-27:00:00+00:00"

    API_DISK_CONFIG = "%s:diskConfig" % ALIAS
    INTERNAL_DISK_CONFIG = "auto_disk_config"

    def __init__(self, ext_mgr):
        super(Disk_config, self).__init__(ext_mgr)
        self.compute_api = compute.API()

    def _extract_resource_from_body(self, res, body,
            singular, singular_template, plural, plural_template):
        """Returns a list of the given resources from the request body.

        The templates passed in are used for XML serialization.
        """
        template = res.environ.get('nova.template')
        if plural in body:
            resources = body[plural]
            if template:
                template.attach(plural_template)
        elif singular in body:
            resources = [body[singular]]
            if template:
                template.attach(singular_template)
        else:
            resources = []

        return resources

    def _GET_servers(self, req, res, body):
        context = req.environ['nova.context']

        servers = self._extract_resource_from_body(res, body,
            singular='server', singular_template=ServerDiskConfigTemplate(),
            plural='servers', plural_template=ServersDiskConfigTemplate())

        # Filter out any servers that already have the key set (most likely
        # from a remote zone)
        servers = filter(lambda s: self.API_DISK_CONFIG not in s, servers)

        # Get DB information for servers
        uuids = [server['id'] for server in servers]
        db_servers = db.instance_get_all_by_filters(context, {'uuid': uuids})
        db_servers = dict([(s['uuid'], s) for s in db_servers])

        for server in servers:
            db_server = db_servers.get(server['id'])
            if db_server:
                value = db_server[self.INTERNAL_DISK_CONFIG]
                server[self.API_DISK_CONFIG] = disk_config_to_api(value)

        return res

    def _GET_images(self, req, res, body):
        images = self._extract_resource_from_body(res, body,
            singular='image', singular_template=ImageDiskConfigTemplate(),
            plural='images', plural_template=ImagesDiskConfigTemplate())

        for image in images:
            metadata = image['metadata']

            if self.INTERNAL_DISK_CONFIG in metadata:
                raw_value = metadata[self.INTERNAL_DISK_CONFIG]
                value = utils.bool_from_str(raw_value)
                image[self.API_DISK_CONFIG] = disk_config_to_api(value)

        return res

    def _POST_servers(self, req, res, body):
        return self._GET_servers(req, res, body)

    def _pre_POST_servers(self, req):
        # NOTE(sirp): deserialization currently occurs *after* pre-processing
        # extensions are called. Until extensions are refactored so that
        # deserialization occurs earlier, we have to perform the
        # deserialization ourselves.
        content_type = req.content_type

        if 'xml' in content_type:
            node = minidom.parseString(req.body)
            server = node.getElementsByTagName('server')[0]
            api_value = server.getAttribute(self.API_DISK_CONFIG)
            if api_value:
                value = disk_config_from_api(api_value)
                server.setAttribute(self.INTERNAL_DISK_CONFIG, str(value))
                req.body = str(node.toxml())
        else:
            body = utils.loads(req.body)
            server = body['server']
            api_value = server.get(self.API_DISK_CONFIG)
            if api_value:
                value = disk_config_from_api(api_value)
                server[self.INTERNAL_DISK_CONFIG] = value
                req.body = utils.dumps(body)

    def _pre_PUT_servers(self, req):
        return self._pre_POST_servers(req)

    def get_request_extensions(self):
        ReqExt = extensions.RequestExtension
        return [
            ReqExt(method='GET',
                   url_route='/:(project_id)/servers/:(id)',
                   handler=self._GET_servers),
            ReqExt(method='POST',
                   url_route='/:(project_id)/servers',
                   handler=self._POST_servers,
                   pre_handler=self._pre_POST_servers),
            ReqExt(method='PUT',
                   url_route='/:(project_id)/servers/:(id)',
                   pre_handler=self._pre_PUT_servers),
            ReqExt(method='GET',
                   url_route='/:(project_id)/images/:(id)',
                   handler=self._GET_images)
        ]
