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
The FilterScheduler is for creating instances locally.
You can customize this scheduler by specifying your own Host Filters and
Weighing Functions.
"""

import random

from oslo_log import log as logging
from six.moves import range

import nova.conf
from nova import exception
from nova.i18n import _
from nova import rpc
from nova.scheduler import client as scheduler_client
from nova.scheduler import driver
from nova.scheduler import utils


CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


class FilterScheduler(driver.Scheduler):
    """Scheduler that can be used for filtering and weighing."""
    def __init__(self, *args, **kwargs):
        super(FilterScheduler, self).__init__(*args, **kwargs)
        self.notifier = rpc.get_notifier('scheduler')
        # TODO(sbauza): It seems weird that we load a scheduler client for
        # the FilterScheduler but it will be the PlacementClient later on once
        # we split the needed methods into a separate library.
        self.scheduler_client = scheduler_client.SchedulerClient()

    def select_destinations(self, context, spec_obj, instance_uuids):
        """Selects a filtered set of hosts and nodes."""
        self.notifier.info(
            context, 'scheduler.select_destinations.start',
            dict(request_spec=spec_obj.to_legacy_request_spec_dict()))

        num_instances = spec_obj.num_instances
        selected_hosts = self._schedule(context, spec_obj, instance_uuids)

        # Couldn't fulfill the request_spec
        if len(selected_hosts) < num_instances:
            # NOTE(Rui Chen): If multiple creates failed, set the updated time
            # of selected HostState to None so that these HostStates are
            # refreshed according to database in next schedule, and release
            # the resource consumed by instance in the process of selecting
            # host.
            for host in selected_hosts:
                host.obj.updated = None

            # Log the details but don't put those into the reason since
            # we don't want to give away too much information about our
            # actual environment.
            LOG.debug('There are %(hosts)d hosts available but '
                      '%(num_instances)d instances requested to build.',
                      {'hosts': len(selected_hosts),
                       'num_instances': num_instances})

            reason = _('There are not enough hosts available.')
            raise exception.NoValidHost(reason=reason)

        dests = [dict(host=host.obj.host, nodename=host.obj.nodename,
                      limits=host.obj.limits) for host in selected_hosts]

        self.notifier.info(
            context, 'scheduler.select_destinations.end',
            dict(request_spec=spec_obj.to_legacy_request_spec_dict()))
        return dests

    def _schedule(self, context, spec_obj, instance_uuids):
        """Returns a list of hosts that meet the required specs,
        ordered by their fitness.
        """
        elevated = context.elevated()

        # Find our local list of acceptable hosts by repeatedly
        # filtering and weighing our options. Each time we choose a
        # host, we virtually consume resources on it so subsequent
        # selections can adjust accordingly.

        # Note: remember, we are using an iterator here. So only
        # traverse this list once. This can bite you if the hosts
        # are being scanned in a filter or weighing function.
        hosts = self._get_all_host_states(elevated, spec_obj)

        selected_hosts = []
        num_instances = spec_obj.num_instances
        for num in range(num_instances):
            # Filter local hosts based on requirements ...
            hosts = self.host_manager.get_filtered_hosts(hosts,
                    spec_obj, index=num)
            if not hosts:
                # Can't get any more locally.
                break

            LOG.debug("Filtered %(hosts)s", {'hosts': hosts})

            weighed_hosts = self.host_manager.get_weighed_hosts(hosts,
                    spec_obj)

            LOG.debug("Weighed %(hosts)s", {'hosts': weighed_hosts})

            host_subset_size = CONF.filter_scheduler.host_subset_size
            if host_subset_size < len(weighed_hosts):
                weighed_hosts = weighed_hosts[0:host_subset_size]
            chosen_host = random.choice(weighed_hosts)

            LOG.debug("Selected host: %(host)s", {'host': chosen_host})
            selected_hosts.append(chosen_host)

            # Now consume the resources so the filter/weights
            # will change for the next instance.
            chosen_host.obj.consume_from_request(spec_obj)
            if spec_obj.instance_group is not None:
                spec_obj.instance_group.hosts.append(chosen_host.obj.host)
                # hosts has to be not part of the updates when saving
                spec_obj.instance_group.obj_reset_changes(['hosts'])
        return selected_hosts

    def _get_all_host_states(self, context, spec_obj):
        """Template method, so a subclass can implement caching."""
        resources = utils.resources_from_request_spec(spec_obj)
        filters = {'resources': resources}
        reportclient = self.scheduler_client.reportclient
        rps = reportclient.get_filtered_resource_providers(filters)
        # NOTE(sbauza): In case the Placement service is not running yet or
        # when returning an exception, we wouldn't get any resource providers.
        # If so, let's return an empty list so _schedule would raise a
        # NoValidHosts.
        if not rps:
            return []
        compute_uuids = [rp['uuid'] for rp in rps]
        return self.host_manager.get_host_states_by_uuids(context,
                                                          compute_uuids,
                                                          spec_obj)
