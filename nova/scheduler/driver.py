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
Scheduler base class that all Schedulers should inherit from
"""

import datetime

from nova import db
from nova import exception
from nova import flags

FLAGS = flags.FLAGS
flags.DEFINE_integer('service_down_time', 60,
                     'maximum time since last checkin for up service')


class NoValidHost(exception.Error):
    """There is no valid host for the command."""
    pass


class WillNotSchedule(exception.Error):
    """The specified host is not up or doesn't exist."""
    pass


class Scheduler(object):
    """The base class that all Scheduler clases should inherit from."""

    @staticmethod
    def service_is_up(service):
        """Check whether a service is up based on last heartbeat."""
        last_heartbeat = service['updated_at'] or service['created_at']
        # Timestamps in DB are UTC.
        elapsed = datetime.datetime.utcnow() - last_heartbeat
        return elapsed < datetime.timedelta(seconds=FLAGS.service_down_time)

    def hosts_up(self, context, topic):
        """Return the list of hosts that have a running service for topic."""

        services = db.service_get_all_by_topic(context, topic)
        return [service.host
                for service in services
                if self.service_is_up(service)]

    def schedule(self, context, topic, *_args, **_kwargs):
        """Must override at least this method for scheduler to work."""
        raise NotImplementedError("Must implement a fallback schedule")
