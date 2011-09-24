# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Openstack, LLC.
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
Availability Zone Scheduler implementation
"""

import random

from nova.scheduler import driver
from nova import db


class ZoneScheduler(driver.Scheduler):
    """Implements Scheduler as a random node selector."""

    def hosts_up_with_zone(self, context, topic, zone):
        """Return the list of hosts that have a running service
        for topic and availability zone (if defined).
        """

        if not zone:
            return self.hosts_up(context, topic)

        services = db.service_get_all_by_topic(context, topic)
        return [service.host
                for service in services
                if self.service_is_up(service)
                and service.availability_zone == zone]

    def _schedule(self, context, topic, request_spec, **kwargs):
        """Picks a host that is up at random in selected
        availability zone (if defined).
        """

        zone = kwargs.get('availability_zone')
        if not zone and request_spec:
            zone = request_spec['instance_properties'].get(
                    'availability_zone')
        hosts = self.hosts_up_with_zone(context.elevated(), topic, zone)
        if not hosts:
            raise driver.NoValidHost(_("Scheduler was unable to locate a host"
                                       " for this request. Is the appropriate"
                                       " service running?"))
        return hosts[int(random.random() * len(hosts))]

    def schedule(self, context, topic, method, *_args, **kwargs):
        host = self._schedule(context, topic, None, **kwargs)
        driver.cast_to_host(context, topic, host, method, **kwargs)

    def schedule_run_instance(self, context, request_spec, *_args, **kwargs):
        """Builds and starts instances on selected hosts"""
        num_instances = request_spec.get('num_instances', 1)
        instances = []
        for num in xrange(num_instances):
            host = self._schedule(context, 'compute', request_spec, **kwargs)
            instance = self.create_instance_db_entry(context, request_spec)
            driver.cast_to_compute_host(context, host,
                    'run_instance', instance_id=instance['id'], **kwargs)
            instances.append(driver.encode_instance(instance))
        return instances
