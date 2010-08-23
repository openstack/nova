# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

from nova import wsgi


class Controller(wsgi.Controller):
    """TODO(eday): Base controller for all rackspace controllers. What is this
    for? Is this just Rackspace specific? """

    @classmethod
    def render(cls, instance):
        if isinstance(instance, list):
            return {cls.entity_name: cls.render(instance)}
        else:
            return { "TODO": "TODO" }
