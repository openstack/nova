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

from nova.api.openstack.compute.schemas import user_data as schema_user_data
from nova.api.openstack import extensions


ALIAS = "os-user-data"
ATTRIBUTE_NAME = 'user_data'


class UserData(extensions.V21APIExtensionBase):
    """Add user_data to the Create Server API."""

    name = "UserData"
    alias = ALIAS
    version = 1

    def get_controller_extensions(self):
        return []

    def get_resources(self):
        return []

    # NOTE(gmann): This function is not supposed to use 'body_deprecated_param'
    # parameter as this is placed to handle scheduler_hint extension for V2.1.
    def server_create(self, server_dict, create_kwargs, body_deprecated_param):
        create_kwargs['user_data'] = server_dict.get(ATTRIBUTE_NAME)

    def get_server_create_schema(self, version):
        return schema_user_data.server_create
