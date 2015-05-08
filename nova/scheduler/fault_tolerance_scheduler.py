# Copyright (c) 2014 Umea University
# Copyright (c) 2011 OpenStack Foundation
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
Perform scheduling of primary/secondary relational VMs.
"""
import random

from oslo.config import cfg

from nova import exception
from nova.openstack.common import log as logging
from nova.openstack.common.gettextutils import _
from nova.scheduler import filter_scheduler

CONF = cfg.CONF
LOG = logging.getLogger(__name__)

ft_scheduler_opts = [
    cfg.IntOpt('ft_scheduler_secondary_instances',
               default=1,
               help='The number of secondary instances that should be created '
                    'when an instance is deployed.')
]
CONF.register_opts(ft_scheduler_opts)
CONF.set_default(
    'scheduler_host_manager',
    'nova.scheduler.fault_tolerance_host_manager.FaultToleranceHostManager')


class FaultToleranceScheduler(filter_scheduler.FilterScheduler):
    """Extends current placement procedure with the ability to
    deploy secondary instances in relation to the primary instance.
    """

    def __init__(self, *args, **kwargs):
        super(FaultToleranceScheduler, self).__init__(*args, **kwargs)

        if CONF.ft_scheduler_secondary_instances < 0:
            raise exception.NovaException(
                    _("Invalid value for 'ft_scheduler_secondary_instances',"
                      " must be >= 0"))

    def select_destinations(self, context, request_spec, filter_properties):
        """Selects sets of hosts weighed together to get the optimal placement
        for relational instances.
        """
        self.notifier.info(context, 'scheduler.select_destinations.start',
                           dict(request_spec=request_spec))

        scheduler_hints = filter_properties.get('scheduler_hints') or {}

        # Secondary hosts are already scheduled
        if 'ft_secondary_host' in scheduler_hints:
            return [scheduler_hints['ft_secondary_host']]

        selected_hostsets = self._schedule(context, request_spec,
                                           filter_properties)

        num_instances = request_spec.get('num_instances', 1)
        # Couldn't fulfill the request_spec
        if len(selected_hostsets) < num_instances:
            raise exception.NoValidHost(reason='')

        dests = []
        for hostset in selected_hostsets:
            dest = dict(host=hostset[0].host,
                        nodename=hostset[0].nodename,
                        limits=hostset[0].limits)

            secondary_hosts = []
            for secondary_host in hostset[1:]:
                secondary_hosts.append(dict(
                    host=secondary_host.host,
                    nodename=secondary_host.nodename,
                    limits=secondary_host.limits))

            if secondary_hosts:
                dest['ft_secondary_hosts'] = secondary_hosts

            dests.append(dest)

        self.notifier.info(context, 'scheduler.select_destinations.end',
                           dict(request_spec=request_spec))
        return dests

    def _schedule(self, context, request_spec, filter_properties):
        """Filters host candidates and (if enough hosts passes the filters)
        creates sets of all possible host combinations. Finally, the hostsets
        are weighed and a list of sets of hosts are returned sorted by their
        weight.
        """
        elevated = context.elevated()
        instance_properties = request_spec['instance_properties']
        instance_type = request_spec.get("instance_type", None)
        instance_uuids = request_spec.get("instance_uuids", None)
        extra_specs = instance_type.get('extra_specs', {})

        update_group_hosts = self._setup_instance_group(context,
                                                        filter_properties)

        config_options = self._get_configuration_options()

        filter_properties.update({'context': context,
                                  'request_spec': request_spec,
                                  'config_options': config_options,
                                  'instance_type': instance_type})

        self.populate_filter_properties(request_spec,
                                        filter_properties)

        # Find our local list of acceptable hosts by repeatedly
        # filtering and weighing our options. Each time we choose a
        # host, we virtually consume resources on it so subsequent
        # selections can adjust accordingly.

        # Note: remember, we are using an iterator here. So only
        # traverse this list once. This can bite you if the hosts
        # are being scanned in a filter or weighing function.
        hosts = self._get_all_host_states(elevated)

        selected_hostsets = []
        if instance_uuids:
            num_instances = len(instance_uuids)
        else:
            num_instances = request_spec.get('num_instances', 1)
        for num in xrange(num_instances):
            if 'ft:enabled' in extra_specs:
                # Scheduling new instance with secondary instances
                size = CONF.ft_scheduler_secondary_instances + 1
            else:
                # Scheduling new instance without fault tolerance
                size = 1

            # Filter local hosts based on requirements ...
            hosts, filtered_hostsets = self.host_manager.get_filtered_hosts(
                    size, hosts, filter_properties, index=num)

            if not filtered_hostsets:
                # Can't get any more locally.
                break

            LOG.debug("Filtered %(hosts)s", {'hosts': filtered_hostsets})

            weighed_hostsets = self.host_manager.get_weighed_hosts(
                    filtered_hostsets, filter_properties)

            LOG.debug("Weighed %(hosts)s", {'hosts': weighed_hostsets})

            scheduler_host_subset_size = CONF.scheduler_host_subset_size
            if scheduler_host_subset_size > len(weighed_hostsets):
                scheduler_host_subset_size = len(weighed_hostsets)
            if scheduler_host_subset_size < 1:
                scheduler_host_subset_size = 1

            chosen_hostset = random.choice(
                weighed_hostsets[0:scheduler_host_subset_size])
            selected_hostsets.append(chosen_hostset)

            # Now consume the resources so the filter/weights
            # will change for the next instance.
            # NOTE (baoli) adding and deleting pci_requests is a temporary
            # fix to avoid DB access in consume_from_instance() while getting
            # pci_requests. The change can be removed once pci_requests is
            # part of the instance object that is passed into the scheduler
            # APIs
            pci_requests = filter_properties.get('pci_requests')
            if pci_requests:
                instance_properties['pci_requests'] = pci_requests

            for host in chosen_hostset:
                host.consume_from_instance(instance_properties)

                # TODO(ORBIT): Unsure if secondary instances should be in
                #              group. Right now both primary and secondary
                #              instances are added since secondary instances
                #              may replace the primary instance.
                if update_group_hosts is True:
                    filter_properties['group_hosts'].add(host.host)

            if pci_requests:
                del instance_properties['pci_requests']

        return selected_hostsets
