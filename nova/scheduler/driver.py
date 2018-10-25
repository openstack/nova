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

import abc

import six

from nova import objects
from nova.scheduler import host_manager
from nova import servicegroup


@six.add_metaclass(abc.ABCMeta)
class Scheduler(object):
    """The base class that all Scheduler classes should inherit from."""

    # TODO(mriedem): We should remove this flag now so that all scheduler
    # drivers, both in-tree and out-of-tree, must rely on placement for
    # scheduling decisions. We're likely going to have more and more code
    # over time that relies on the scheduler creating allocations and it
    # will not be sustainable to try and keep compatibility code around for
    # scheduler drivers that do not create allocations in Placement.
    USES_ALLOCATION_CANDIDATES = True
    """Indicates that the scheduler driver calls the Placement API for
    allocation candidates and uses those allocation candidates in its
    decision-making.
    """

    def __init__(self):
        self.host_manager = host_manager.HostManager()
        self.servicegroup_api = servicegroup.API()

    def run_periodic_tasks(self, context):
        """Manager calls this so drivers can perform periodic tasks."""
        pass

    def hosts_up(self, context, topic):
        """Return the list of hosts that have a running service for topic."""

        services = objects.ServiceList.get_by_topic(context, topic)
        return [service.host
                for service in services
                if self.servicegroup_api.service_is_up(service)]

    @abc.abstractmethod
    def select_destinations(self, context, spec_obj, instance_uuids,
            alloc_reqs_by_rp_uuid, provider_summaries,
            allocation_request_version=None, return_alternates=False):
        """Returns a list of lists of Selection objects that have been chosen
        by the scheduler driver, one for each requested instance.
        """
        return []
