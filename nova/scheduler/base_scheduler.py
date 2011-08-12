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
        instance_type = request_spec['instance_type']
        name, query = selected_filter.instance_type_to_filter(instance_type)
        return selected_filter.filter_hosts(self.zone_manager, query)

    def filter_hosts(self, topic, request_spec, host_list=None):
        """Return a list of hosts which are acceptable for scheduling.
        Return value should be a list of (hostname, capability_dict)s.
        Derived classes may override this, but may find the
        '<topic>_filter' function more appropriate.
        """
        def _default_filter(self, hostname, capabilities, request_spec):
            """Default filter function if there's no <topic>_filter"""
            # NOTE(sirp): The default logic is the equivalent to
            # AllHostsFilter
            return True

        filter_func = getattr(self, '%s_filter' % topic, _default_filter)

        if host_list is None:
            first_run = True
            host_list = self.zone_manager.service_states.iteritems()
        else:
            first_run = False

        filtered_hosts = []
        for host, services in host_list:
            if first_run:
                if topic not in services:
                    continue
                services = services[topic]
            if filter_func(host, services, request_spec):
                filtered_hosts.append((host, services))
        return filtered_hosts

    def weigh_hosts(self, topic, request_spec, hosts):
        """Derived classes may override this to provide more sophisticated
        scheduling objectives
        """
        # NOTE(sirp): The default logic is the same as the NoopCostFunction
        return [dict(weight=1, hostname=hostname, capabilities=capabilities)
                for hostname, capabilities in hosts]

    def compute_consume(self, capabilities, instance_type):
        """Consume compute resources for selected host"""

        requested_mem = max(instance_type['memory_mb'], 0) * 1024 * 1024
        capabilities['host_memory_free'] -= requested_mem

    def consume_resources(self, topic, capabilities, instance_type):
        """Consume resources for a specific host.  'host' is a tuple
        of the hostname and the services"""

        consume_func = getattr(self, '%s_consume' % topic, None)
        if not consume_func:
            return
        consume_func(capabilities, instance_type)
