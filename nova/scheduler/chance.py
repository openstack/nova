# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 OpenStack, LLC.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""
Chance (Random) Scheduler implementation
"""

import random

from nova import exception
from nova import flags
from nova.scheduler import driver

FLAGS = flags.FLAGS


class ChanceScheduler(driver.Scheduler):
    """Implements Scheduler as a random node selector."""

    def _filter_hosts(self, request_spec, hosts, filter_properties):
        """Filter a list of hosts based on request_spec."""

        ignore_hosts = filter_properties.get('ignore_hosts', [])
        hosts = [host for host in hosts if host not in ignore_hosts]
        return hosts

    def _schedule(self, context, topic, request_spec, filter_properties):
        """Picks a host that is up at random."""

        elevated = context.elevated()
        hosts = self.hosts_up(elevated, topic)
        if not hosts:
            msg = _("Is the appropriate service running?")
            raise exception.NoValidHost(reason=msg)

        hosts = self._filter_hosts(request_spec, hosts, filter_properties)
        if not hosts:
            msg = _("Could not find another compute")
            raise exception.NoValidHost(reason=msg)

        return hosts[int(random.random() * len(hosts))]

    def schedule_run_instance(self, context, request_spec,
                              admin_password, injected_files,
                              requested_networks, is_first_time,
                              filter_properties):
        """Create and run an instance or instances"""
        instance_uuids = request_spec.get('instance_uuids')
        for num, instance_uuid in enumerate(instance_uuids):
            request_spec['instance_properties']['launch_index'] = num
            try:
                host = self._schedule(context, 'compute', request_spec,
                                      filter_properties)
                updated_instance = driver.instance_update_db(context,
                        instance_uuid)
                self.compute_rpcapi.run_instance(context,
                        instance=updated_instance, host=host,
                        requested_networks=requested_networks,
                        injected_files=injected_files,
                        admin_password=admin_password,
                        is_first_time=is_first_time,
                        request_spec=request_spec,
                        filter_properties=filter_properties)
            except Exception as ex:
                # NOTE(vish): we don't reraise the exception here to make sure
                #             that all instances in the request get set to
                #             error properly
                driver.handle_schedule_error(context, ex, instance_uuid,
                                             request_spec)

    def schedule_prep_resize(self, context, image, request_spec,
                             filter_properties, instance, instance_type,
                             reservations):
        """Select a target for resize."""
        host = self._schedule(context, 'compute', request_spec,
                              filter_properties)
        self.compute_rpcapi.prep_resize(context, image, instance,
                instance_type, host, reservations)

    def schedule_create_volume(self, context, volume_id, snapshot_id,
                               image_id):
        """Picks a host that is up at random."""
        host = self._schedule(context, FLAGS.volume_topic, None, {})
        driver.cast_to_host(context, FLAGS.volume_topic, host, 'create_volume',
                            volume_id=volume_id, snapshot_id=snapshot_id,
                            image_id=image_id)
