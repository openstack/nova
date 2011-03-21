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

import json

from nova import wsgi

from nova.api.openstack import extensions


class FoxInSocksController(wsgi.Controller):

    def index(self, req):
        return "Try to say this Mr. Knox, sir..."


class Foxinsocks(object):

    def __init__(self):
        pass

    def get_name(self):
        return "Fox In Socks"

    def get_alias(self):
        return "FOXNSOX"

    def get_description(self):
        return "The Fox In Socks Extension"

    def get_namespace(self):
        return "http://www.fox.in.socks/api/ext/pie/v1.0"

    def get_updated(self):
        return "2011-01-22T13:25:27-06:00"

    def get_resources(self):
        resources = []
        resource = extensions.ResourceExtension('foxnsocks',
                                               FoxInSocksController())
        resources.append(resource)
        return resources

    def get_actions(self):
        actions = []
        actions.append(extensions.ActionExtension('servers', 'add_tweedle',
                                                    self._add_tweedle))
        actions.append(extensions.ActionExtension('servers', 'delete_tweedle',
                                                    self._delete_tweedle))
        return actions

    def get_response_extensions(self):
        response_exts = []

        def _goose_handler(res):
            #NOTE: This only handles JSON responses.
            # You can use content type header to test for XML.
            data = json.loads(res.body)
            data['flavor']['googoose'] = "Gooey goo for chewy chewing!"
            return data

        resp_ext = extensions.ResponseExtension('GET', '/v1.0/flavors/:(id)',
                                                _goose_handler)
        response_exts.append(resp_ext)

        def _bands_handler(res):
            #NOTE: This only handles JSON responses.
            # You can use content type header to test for XML.
            data = json.loads(res.body)
            data['big_bands'] = 'Pig Bands!'
            return data

        resp_ext2 = extensions.ResponseExtension('GET', '/v1.0/flavors/:(id)',
                                                _bands_handler)
        response_exts.append(resp_ext2)
        return response_exts

    def _add_tweedle(self, input_dict, req, id):

        return "Tweedle Beetle Added."

    def _delete_tweedle(self, input_dict, req, id):

        return "Tweedle Beetle Deleted."
