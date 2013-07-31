# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 IBM Corp.
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

import webob.exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)


def make_ext(elem):
    elem.set('name')
    elem.set('namespace')
    elem.set('alias')
    elem.set('version')

    desc = xmlutil.SubTemplateElement(elem, 'description')
    desc.text = 'description'


ext_nsmap = {None: xmlutil.XMLNS_COMMON_V10, 'atom': xmlutil.XMLNS_ATOM}


class ExtensionTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('extension', selector='extension')
        make_ext(root)
        return xmlutil.MasterTemplate(root, 1, nsmap=ext_nsmap)


class ExtensionsTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('extensions')
        elem = xmlutil.SubTemplateElement(root, 'extension',
                                          selector='extensions')
        make_ext(elem)
        return xmlutil.MasterTemplate(root, 1, nsmap=ext_nsmap)


class ExtensionInfoController(object):

    def __init__(self, extension_info):
        self.extension_info = extension_info

    def _translate(self, ext):
        ext_data = {}
        ext_data['name'] = ext.name
        ext_data['alias'] = ext.alias
        ext_data['description'] = ext.__doc__
        ext_data['namespace'] = ext.namespace
        ext_data['version'] = ext.version
        return ext_data

    def _get_extensions(self, context):
        """Filter extensions list based on policy."""

        discoverable_extensions = dict()
        for alias, ext in self.extension_info.get_extensions().iteritems():
            authorize = extensions.soft_extension_authorizer(
                'compute', 'v3:' + alias)
            if authorize(context, action='discoverable'):
                discoverable_extensions[alias] = ext
            else:
                LOG.debug(_("Filter out extension %s from discover list"),
                          alias)
        return discoverable_extensions

    @extensions.expected_errors(())
    @wsgi.serializers(xml=ExtensionsTemplate)
    def index(self, req):
        context = req.environ['nova.context']

        sorted_ext_list = sorted(
            self._get_extensions(context).iteritems())

        extensions = []
        for _alias, ext in sorted_ext_list:
            extensions.append(self._translate(ext))
        return dict(extensions=extensions)

    @extensions.expected_errors(404)
    @wsgi.serializers(xml=ExtensionTemplate)
    def show(self, req, id):
        context = req.environ['nova.context']
        try:
            # NOTE(dprince): the extensions alias is used as the 'id' for show
            ext = self._get_extensions(context)[id]
        except KeyError:
            raise webob.exc.HTTPNotFound()

        return dict(extension=self._translate(ext))


class ExtensionInfo(extensions.V3APIExtensionBase):
    """Extension information."""

    name = "extensions"
    alias = "extensions"
    namespace = "http://docs.openstack.org/compute/core/extension_info/api/v3"
    version = 1

    def get_resources(self):
        resources = [
            extensions.ResourceExtension(
                'extensions', ExtensionInfoController(self.extension_info),
                member_name='extension')]
        return resources

    def get_controller_extensions(self):
        return []
