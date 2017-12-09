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
Chance (Random) Scheduler implementation
"""

import random

from oslo_log import log as logging

from nova.compute import rpcapi as compute_rpcapi
import nova.conf
from nova import exception
from nova.i18n import _
from nova import objects
from nova.scheduler import driver

CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


class ChanceScheduler(driver.Scheduler):
    """Implements Scheduler as a random node selector."""

    USES_ALLOCATION_CANDIDATES = False

    def __init__(self, *args, **kwargs):
        super(ChanceScheduler, self).__init__(*args, **kwargs)
        LOG.warning('ChanceScheduler is deprecated in Pike and will be '
                    'removed in a subsequent release.')

    def _filter_hosts(self, hosts, spec_obj):
        """Filter a list of hosts based on RequestSpec."""

        ignore_hosts = spec_obj.ignore_hosts or []
        hosts = [host for host in hosts if host not in ignore_hosts]
        return hosts

    def _schedule(self, context, topic, spec_obj, instance_uuids,
            return_alternates=False):
        """Picks a host that is up at random."""

        elevated = context.elevated()
        hosts = self.hosts_up(elevated, topic)
        if not hosts:
            msg = _("Is the appropriate service running?")
            raise exception.NoValidHost(reason=msg)

        hosts = self._filter_hosts(hosts, spec_obj)
        if not hosts:
            msg = _("Could not find another compute")
            raise exception.NoValidHost(reason=msg)

        # Note that we don't claim in the chance scheduler
        num_instances = len(instance_uuids)
        # If possible, we'd like to return distinct hosts for each instance.
        # But when there are fewer available hosts than requested instances, we
        # will need to return some duplicates.
        if len(hosts) >= num_instances:
            selected_hosts = random.sample(hosts, num_instances)
        else:
            selected_hosts = [random.choice(hosts)
                    for i in range(num_instances)]

        # This is the overall list of values to be returned. There will be one
        # item per instance, and that item will be a list of Selection objects
        # representing the selected host and zero or more alternates.
        # NOTE(edleafe): in a multi-cell environment, this can return
        # alternates from different cells. When support for multiple cells is
        # implemented in select_destinations, this will have to be updated to
        # restrict alternates to come from the same cell.
        selections_to_return = []

        # We can't return dupes as alternates, since alternates are used when
        # building to the selected host fails.
        if return_alternates:
            alts_per_instance = min(len(hosts), CONF.scheduler.max_attempts)
        else:
            alts_per_instance = 0
        for sel_host in selected_hosts:
            selection = objects.Selection.from_host_state(sel_host)
            sel_plus_alts = [selection]
            while len(sel_plus_alts) < alts_per_instance:
                candidate = random.choice(hosts)
                if (candidate not in sel_plus_alts) and (
                        candidate not in selected_hosts):
                    # We don't want to include a selected host as an alternate,
                    # as it will have a high likelihood of not having enough
                    # resources left after it has an instance built on it.
                    alt_select = objects.Selection.from_host_state(candidate)
                    sel_plus_alts.append(alt_select)
            selections_to_return.append(sel_plus_alts)
        return selections_to_return

    def select_destinations(self, context, spec_obj, instance_uuids,
            alloc_reqs_by_rp_uuid, provider_summaries,
            allocation_request_version=None, return_alternates=False):
        """Selects random destinations. Returns a list of list of Selection
        objects.
        """
        num_instances = spec_obj.num_instances
        # TODO(danms): This needs to be extended to support multiple cells
        # and limiting the destination scope to a single requested cell
        host_selections = self._schedule(context, compute_rpcapi.RPC_TOPIC,
                spec_obj, instance_uuids)
        if len(host_selections) < num_instances:
            reason = _('There are not enough hosts available.')
            raise exception.NoValidHost(reason=reason)
        return host_selections
