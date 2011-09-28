# Copyright (c) 2011 Openstack, LLC.
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
The BaseScheduler is the base class Scheduler for creating instances
across zones. There are two expansion points to this class for:
1. Assigning Weights to hosts for requested instances
2. Filtering Hosts based on required instance capabilities
"""

from nova import flags
from nova import log as logging

from nova.scheduler import abstract_scheduler
from nova.scheduler import host_filter

FLAGS = flags.FLAGS
LOG = logging.getLogger('nova.scheduler.base_scheduler')


class BaseScheduler(abstract_scheduler.AbstractScheduler):
    """Base class for creating Schedulers that can work across any nova
    deployment, from simple designs to multiply-nested zones.
    """
    def filter_hosts(self, topic, request_spec, hosts=None):
        """Filter the full host list (from the ZoneManager)"""
        filter_name = request_spec.get('filter', None)
        # Make sure that the requested filter is legitimate.
        selected_filter = host_filter.choose_host_filter(filter_name)

        # TODO(sandy): We're only using InstanceType-based specs
        # currently. Later we'll need to snoop for more detailed
        # host filter requests.
        instance_type = request_spec.get("instance_type", None)
        if instance_type is None:
            # No way to select; return the specified hosts
            return hosts or []
        name, query = selected_filter.instance_type_to_filter(instance_type)
        return selected_filter.filter_hosts(self.zone_manager, query)

    def weigh_hosts(self, topic, request_spec, hosts):
        """Derived classes may override this to provide more sophisticated
        scheduling objectives
        """
        # Make sure if there are compute hosts to serve the request.
        if not hosts:
            return []
        # NOTE(sirp): The default logic is the same as the NoopCostFunction
        hosts = [dict(weight=1, hostname=hostname, capabilities=capabilities)
                 for hostname, capabilities in hosts]

        # NOTE(Vek): What we actually need to return is enough hosts
        #            for all the instances!
        num_instances = request_spec.get('num_instances', 1)
        instances = []
        while num_instances > len(hosts):
            instances.extend(hosts)
            num_instances -= len(hosts)
        if num_instances > 0:
            instances.extend(hosts[:num_instances])

        return instances
