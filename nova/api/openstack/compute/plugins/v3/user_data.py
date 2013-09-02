# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack Foundation
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

from nova.api.openstack import extensions


ALIAS = "os-user-data"
ATTRIBUTE_NAME = '%s:user_data' % ALIAS


class UserData(extensions.V3APIExtensionBase):
    """Add user_data to the Create Server v1.1 API."""

    name = "UserData"
    alias = "os-user-data"
    namespace = ("http://docs.openstack.org/compute/ext/"
                 "userdata/api/v3")
    version = 1

    def get_controller_extensions(self):
        return []

    def get_resources(self):
        return []

    def server_create(self, server_dict, create_kwargs):
        create_kwargs['user_data'] = server_dict.get(ATTRIBUTE_NAME)

    def server_xml_extract_server_deserialize(self, server_node, server_dict):
        user_data = server_node.getAttribute(ATTRIBUTE_NAME)
        if user_data:
            server_dict[ATTRIBUTE_NAME] = user_data
