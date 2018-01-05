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

from oslo_log import log as logging
from oslo_serialization import jsonutils

from nova import availability_zones
from nova.conductor.tasks import base
from nova import objects
from nova.scheduler import utils as scheduler_utils

LOG = logging.getLogger(__name__)


class MigrationTask(base.TaskBase):
    def __init__(self, context, instance, flavor,
                 request_spec, reservations, clean_shutdown, compute_rpcapi,
                 scheduler_client):
        super(MigrationTask, self).__init__(context, instance)
        self.clean_shutdown = clean_shutdown
        self.request_spec = request_spec
        self.reservations = reservations
        self.flavor = flavor

        self.compute_rpcapi = compute_rpcapi
        self.scheduler_client = scheduler_client

    def _execute(self):
        # TODO(sbauza): Remove that once prep_resize() accepts a  RequestSpec
        # object in the signature and all the scheduler.utils methods too
        legacy_spec = self.request_spec.to_legacy_request_spec_dict()
        legacy_props = self.request_spec.to_legacy_filter_properties_dict()
        scheduler_utils.setup_instance_group(self.context, self.request_spec)
        scheduler_utils.populate_retry(legacy_props,
                                       self.instance.uuid)

        # NOTE(sbauza): Force_hosts/nodes needs to be reset
        # if we want to make sure that the next destination
        # is not forced to be the original host
        self.request_spec.reset_forced_destinations()

        # NOTE(danms): Right now we only support migrate to the same
        # cell as the current instance, so request that the scheduler
        # limit thusly.
        instance_mapping = objects.InstanceMapping.get_by_instance_uuid(
            self.context, self.instance.uuid)
        LOG.debug('Requesting cell %(cell)s while migrating',
                  {'cell': instance_mapping.cell_mapping.identity},
                  instance=self.instance)
        if ('requested_destination' in self.request_spec and
                self.request_spec.requested_destination):
            self.request_spec.requested_destination.cell = (
                instance_mapping.cell_mapping)
        else:
            self.request_spec.requested_destination = objects.Destination(
                cell=instance_mapping.cell_mapping)

        self.request_spec.ensure_project_id(self.instance)
        hosts = self.scheduler_client.select_destinations(
            self.context, self.request_spec, [self.instance.uuid])
        host_state = hosts[0]

        scheduler_utils.populate_filter_properties(legacy_props,
                                                   host_state)
        # context is not serializable
        legacy_props.pop('context', None)

        (host, node) = (host_state['host'], host_state['nodename'])

        self.instance.availability_zone = (
            availability_zones.get_host_availability_zone(
                self.context, host))

        # FIXME(sbauza): Serialize/Unserialize the legacy dict because of
        # oslo.messaging #1529084 to transform datetime values into strings.
        # tl;dr: datetimes in dicts are not accepted as correct values by the
        # rpc fake driver.
        legacy_spec = jsonutils.loads(jsonutils.dumps(legacy_spec))

        self.compute_rpcapi.prep_resize(
            self.context, self.instance, legacy_spec['image'],
            self.flavor, host, self.reservations,
            request_spec=legacy_spec, filter_properties=legacy_props,
            node=node, clean_shutdown=self.clean_shutdown)

    def rollback(self):
        pass
