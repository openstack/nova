# Copyright 2014 NEC Corporation.  All rights reserved.
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

from nova.api.openstack.compute.schemas import personality
from nova.api.openstack import extensions

ALIAS = "os-personality"


class Personality(extensions.V21APIExtensionBase):
    """Personality support."""

    name = "Personality"
    alias = ALIAS
    version = 1

    def get_controller_extensions(self):
        return []

    def get_resources(self):
        return []

    def _get_injected_files(self, personality):
        """Create a list of injected files from the personality attribute.

        At this time, injected_files must be formatted as a list of
        (file_path, file_content) pairs for compatibility with the
        underlying compute service.
        """
        injected_files = []
        for item in personality:
            injected_files.append((item['path'], item['contents']))
        return injected_files

    # Extend server in both create & rebuild
    #
    # TODO(sdague): it looks weird that server_create is different
    # than server_rebuild, right? Well you can totally blame hooks for
    # that. By accident this means that server personalities are
    # always creating the injected_files kwarg, even if there is
    # nothing in it. Hooks totally needs injected_files to be a
    # thing. Once hooks are removed from tree, this function can be
    # made to look like the rebuild one.
    def server_create(self, server_dict, create_kwargs, body_deprecated):
        create_kwargs['injected_files'] = self._get_injected_files(
            server_dict.get('personality', []))

    def server_rebuild(self, server_dict, create_kwargs):
        if 'personality' in server_dict:
            create_kwargs['files_to_inject'] = self._get_injected_files(
                                                  server_dict['personality'])

    # Extend schema with the new allowed parameters
    def get_server_create_schema(self, version):
        return personality.server_create

    def get_server_rebuild_schema(self, version):
        return personality.server_create
