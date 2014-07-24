# Copyright 2011 OpenStack Foundation
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

import webob.exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi


class FoxInSocksController(object):

    def index(self, req):
        return "Try to say this Mr. Knox, sir..."


class FoxInSocksServerControllerExtension(wsgi.Controller):
    @wsgi.action('add_tweedle')
    def _add_tweedle(self, req, id, body):

        return "Tweedle Beetle Added."

    @wsgi.action('delete_tweedle')
    def _delete_tweedle(self, req, id, body):

        return "Tweedle Beetle Deleted."

    @wsgi.action('fail')
    def _fail(self, req, id, body):

        raise webob.exc.HTTPBadRequest(explanation='Tweedle fail')


class FoxInSocksFlavorGooseControllerExtension(wsgi.Controller):
    @wsgi.extends
    def show(self, req, resp_obj, id):
        # NOTE: This only handles JSON responses.
        # You can use content type header to test for XML.
        resp_obj.obj['flavor']['googoose'] = req.GET.get('chewing')


class FoxInSocksFlavorBandsControllerExtension(wsgi.Controller):
    @wsgi.extends
    def show(self, req, resp_obj, id):
        # NOTE: This only handles JSON responses.
        # You can use content type header to test for XML.
        resp_obj.obj['big_bands'] = 'Pig Bands!'


class Foxinsocks(extensions.ExtensionDescriptor):
    """The Fox In Socks Extension."""

    name = "Fox In Socks"
    alias = "FOXNSOX"
    namespace = "http://www.fox.in.socks/api/ext/pie/v1.0"
    updated = "2011-01-22T13:25:27-06:00"

    def __init__(self, ext_mgr):
        ext_mgr.register(self)

    def get_resources(self):
        resources = []
        resource = extensions.ResourceExtension('foxnsocks',
                                               FoxInSocksController())
        resources.append(resource)
        return resources

    def get_controller_extensions(self):
        extension_list = []

        extension_set = [
            (FoxInSocksServerControllerExtension, 'servers'),
            (FoxInSocksFlavorGooseControllerExtension, 'flavors'),
            (FoxInSocksFlavorBandsControllerExtension, 'flavors'),
            ]
        for klass, collection in extension_set:
            controller = klass()
            ext = extensions.ControllerExtension(self, collection, controller)
            extension_list.append(ext)

        return extension_list
