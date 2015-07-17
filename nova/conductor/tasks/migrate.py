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

from nova.conductor.tasks import base
from nova import objects
from nova.scheduler import utils as scheduler_utils


class MigrationTask(base.TaskBase):
    def __init__(self, context, instance, flavor, filter_properties,
                 request_spec, reservations, clean_shutdown, compute_rpcapi,
                 scheduler_client):
        super(MigrationTask, self).__init__(context, instance)
        self.clean_shutdown = clean_shutdown
        self.request_spec = request_spec
        self.reservations = reservations
        self.filter_properties = filter_properties
        self.flavor = flavor
        self.quotas = None

        self.compute_rpcapi = compute_rpcapi
        self.scheduler_client = scheduler_client

    def _execute(self):
        image = self.request_spec.get('image')
        self.quotas = objects.Quotas.from_reservations(self.context,
                                                       self.reservations,
                                                       instance=self.instance)
        scheduler_utils.setup_instance_group(self.context, self.request_spec,
                                             self.filter_properties)
        scheduler_utils.populate_retry(self.filter_properties,
                                       self.instance.uuid)
        # TODO(sbauza): Hydrate here the object until we modify the
        # scheduler.utils methods to directly use the RequestSpec object
        spec_obj = objects.RequestSpec.from_primitives(
            self.context, self.request_spec, self.filter_properties)
        hosts = self.scheduler_client.select_destinations(
            self.context, spec_obj)
        host_state = hosts[0]

        scheduler_utils.populate_filter_properties(self.filter_properties,
                                                   host_state)
        # context is not serializable
        self.filter_properties.pop('context', None)

        (host, node) = (host_state['host'], host_state['nodename'])
        self.compute_rpcapi.prep_resize(
            self.context, image, self.instance, self.flavor, host,
            self.reservations, request_spec=self.request_spec,
            filter_properties=self.filter_properties, node=node,
            clean_shutdown=self.clean_shutdown)

    def rollback(self):
        if self.quotas:
            self.quotas.rollback()
