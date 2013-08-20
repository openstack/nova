# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 IBM Corp.
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

import base64
from webob import exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.openstack.common.gettextutils import _
import re

ALIAS = "os-personality"


class Deserializer(wsgi.MetadataXMLDeserializer):

    def extract_personality(self, server_node):
        """Marshal the personality attribute of a parsed request."""
        node = self.find_first_child_named(server_node, "personality")
        if node is not None:
            personality = []
            for file_node in self.find_children_named(node, "file"):
                item = {}
                if file_node.hasAttribute("path"):
                    item["path"] = file_node.getAttribute("path")
                item["contents"] = self.extract_text(file_node)
                personality.append(item)
            return personality
        else:
            return None


class Personalities(extensions.V3APIExtensionBase):
    """Personalities Extension."""

    name = "Personalities"
    alias = ALIAS
    namespace = "http://docs.openstack.org/compute/ext/Personalities/api/v3"
    version = 1

    deserializer = Deserializer()

    def get_controller_extensions(self):
        return []

    def get_resources(self):
        return []

    def server_create(self, server_dict, create_kwargs):
        personality = server_dict.get('personality', None)
        injected_files = []
        if personality is not None:
            injected_files = self._get_injected_files(personality)
            create_kwargs['injected_files'] = injected_files

    def server_xml_extract_server_deserialize(self, server_node, server_dict):
        personality = self.deserializer.extract_personality(server_node)
        if personality is not None:
            server_dict["personality"] = personality

    def _get_injected_files(self, personality):
        """Create a list of injected files from the personality attribute.
        At this time, injected_files must be formatted as a list of
        (file_path, file_content) pairs for compatibility with the
        underlying compute service.
        """
        injected_files = []

        for item in personality:
            try:
                path = item['path']
                contents = item['contents']
            except KeyError as key:
                expl = _('Bad personality format: missing %s') % key
                raise exc.HTTPBadRequest(explanation=expl)
            except TypeError:
                expl = _('Bad personality format')
                raise exc.HTTPBadRequest(explanation=expl)
            if self._decode_base64(contents) is None:
                expl = _('Personality content for %s cannot be decoded') % path
                raise exc.HTTPBadRequest(explanation=expl)
            injected_files.append((path, contents))
        return injected_files

    B64_REGEX = re.compile('^(?:[A-Za-z0-9+\/]{4})*'
                           '(?:[A-Za-z0-9+\/]{2}=='
                           '|[A-Za-z0-9+\/]{3}=)?$')

    def _decode_base64(self, data):
        data = re.sub(r'\s', '', data)
        if not self.B64_REGEX.match(data):
            return None
        try:
            return base64.b64decode(data)
        except TypeError:
            return None

    def server_rebuild(self, rebuild_dict, rebuild_kwargs):
        if 'personality' in rebuild_dict:
            personality = rebuild_dict['personality']
            rebuild_kwargs['files_to_inject'] =\
                self._get_injected_files(personality)

    def server_xml_extract_rebuild_deserialize(self,
                                               rebuild_node,
                                               rebuild_dict):
        personality = self.deserializer.extract_personality(rebuild_node)
        if personality is not None:
            rebuild_dict["personality"] = personality
