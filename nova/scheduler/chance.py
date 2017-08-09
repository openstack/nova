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

    def _schedule(self, context, topic, spec_obj):
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

        return random.choice(hosts)

    def select_destinations(self, context, spec_obj, instance_uuids,
            alloc_reqs_by_rp_uuid, provider_summaries):
        """Selects random destinations."""
        num_instances = spec_obj.num_instances
        # NOTE(timello): Returns a list of dicts with 'host', 'nodename' and
        # 'limits' as keys for compatibility with filter_scheduler.
        # TODO(danms): This needs to be extended to support multiple cells
        # and limiting the destination scope to a single requested cell
        dests = []
        for i in range(num_instances):
            host = self._schedule(context, compute_rpcapi.RPC_TOPIC,
                                  spec_obj)
            host_state = self.host_manager.host_state_cls(host, None, None)
            dests.append(host_state)

        if len(dests) < num_instances:
            reason = _('There are not enough hosts available.')
            raise exception.NoValidHost(reason=reason)
        return dests
