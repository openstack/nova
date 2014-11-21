# Copyright 2014 IBM Corp.
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

"""Basic Test Extension"""

from nova.api.openstack import extensions
from nova.api.openstack import wsgi


ALIAS = 'test-basic'


class BasicController(wsgi.Controller):

    def index(self, req):
        data = {'param': 'val'}
        return data


class Basic(extensions.V3APIExtensionBase):
    """Basic Test Extension."""

    name = "BasicTest"
    alias = ALIAS
    version = 1

    def get_resources(self):
        resource = extensions.ResourceExtension('test', BasicController())
        return [resource]

    def get_controller_extensions(self):
        return []
