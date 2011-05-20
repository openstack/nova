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

        if zone is None:
            return self.hosts_up(context, topic)

        services = db.service_get_all_by_topic(context, topic)
        return [service.host
                for service in services
                if self.service_is_up(service)
                and service.availability_zone == zone]

    def schedule(self, context, topic, *_args, **_kwargs):
        """Picks a host that is up at random in selected
        availability zone (if defined).
        """

        zone = _kwargs.get('availability_zone')
        hosts = self.hosts_up_with_zone(context, topic, zone)
        if not hosts:
            raise driver.NoValidHost(_("Scheduler was unable to locate a host"
                                       " for this request. Is the appropriate"
                                       " service running?"))

        return hosts[int(random.random() * len(hosts))]
