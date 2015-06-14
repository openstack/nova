# Copyright (c) 2010 OpenStack Foundation
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

from oslo_config import cfg
from oslo_utils import importutils

from nova import db
from nova.i18n import _
from nova import servicegroup

scheduler_driver_opts = [
    cfg.StrOpt('scheduler_host_manager',
               default='nova.scheduler.host_manager.HostManager',
               help='The scheduler host manager class to use'),
    ]

CONF = cfg.CONF
CONF.register_opts(scheduler_driver_opts)


class Scheduler(object):
    """The base class that all Scheduler classes should inherit from."""

    def __init__(self):
        self.host_manager = importutils.import_object(
                CONF.scheduler_host_manager)
        self.servicegroup_api = servicegroup.API()

    def run_periodic_tasks(self, context):
        """Manager calls this so drivers can perform periodic tasks."""
        pass

    def hosts_up(self, context, topic):
        """Return the list of hosts that have a running service for topic."""

        services = db.service_get_all_by_topic(context, topic)
        return [service['host']
                for service in services
                if self.servicegroup_api.service_is_up(service)]

    def select_destinations(self, context, request_spec, filter_properties):
        """Must override select_destinations method.

        :return: A list of dicts with 'host', 'nodename' and 'limits' as keys
            that satisfies the request_spec and filter_properties.
        """
        msg = _("Driver must implement select_destinations")
        raise NotImplementedError(msg)
