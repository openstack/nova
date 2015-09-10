# Copyright 2011 OpenStack Foundation
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

from nova.api.openstack.compute.schemas import scheduler_hints as schema
from nova.api.openstack import extensions

ALIAS = "os-scheduler-hints"


class SchedulerHints(extensions.V21APIExtensionBase):
    """Pass arbitrary key/value pairs to the scheduler."""

    name = "SchedulerHints"
    alias = ALIAS
    version = 1

    def get_controller_extensions(self):
        return []

    def get_resources(self):
        return []

    # NOTE(gmann): Accepting request body in this function to fetch "scheduler
    # hint". This is a workaround to allow OS_SCH-HNT at the top level
    # of the body request, but that it will be changed in the future to be a
    # subset of the servers dict.
    def server_create(self, server_dict, create_kwargs, req_body):
        scheduler_hints = {}
        if 'os:scheduler_hints' in req_body:
            scheduler_hints = req_body['os:scheduler_hints']
        elif 'OS-SCH-HNT:scheduler_hints' in req_body:
            scheduler_hints = req_body['OS-SCH-HNT:scheduler_hints']

        create_kwargs['scheduler_hints'] = scheduler_hints

    def get_server_create_schema(self, version):
        return schema.server_create
