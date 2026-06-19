# Copyright 2025 Rackspace Technology, Inc.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Scheduler filters for network group affinity and anti-affinity.

These filters constrain instance placement based on the physical network
group (VLAN group / cabinet switch pair) that an Ironic node belongs to.

The network group is specified in a server group's ``rules`` field at
creation time and is matched against ``CUSTOM_NETGROUP_*`` traits reported
by Ironic nodes via the Placement service.
"""

from oslo_log import log as logging

from nova.scheduler import filters

LOG = logging.getLogger(__name__)

# Prefix used when converting a network group name to a trait.
# Example: "a1-1-network" -> "CUSTOM_NETGROUP_A1_1_NETWORK"
_TRAIT_PREFIX = "CUSTOM_NETGROUP_"


def _network_group_to_trait(network_group):
    """Convert a network group name to its corresponding Placement trait.

    :param network_group: The network group name (e.g. "a1-1-network")
    :returns: The trait string (e.g. "CUSTOM_NETGROUP_A1_1_NETWORK")
    """
    normalised = network_group.upper().replace("-", "_").replace("/", "_")
    return _TRAIT_PREFIX + normalised


class NetworkGroupAffinityFilter(filters.BaseHostFilter):
    """Schedule instances onto hosts within a specific network group.

    When a server group has the ``network-group-affinity`` policy and a
    ``network_group`` rule, this filter only passes hosts whose reported
    traits include the matching ``CUSTOM_NETGROUP_*`` trait.

    Hosts without the required trait are rejected.
    """

    # The trait set of a host does not change within a single scheduling
    # request.
    run_filter_once_per_request = True

    RUN_ON_REBUILD = False

    def host_passes(self, host_state, spec_obj):
        instance_group = spec_obj.instance_group
        if not instance_group:
            return True

        policy = instance_group.policy if instance_group else None
        if policy != 'network-group-affinity':
            return True

        rules = instance_group.rules
        network_group = rules.get('network_group') if rules else None
        if not network_group:
            return True

        required_trait = _network_group_to_trait(network_group)

        host_traits = set()
        if hasattr(host_state, 'traits'):
            host_traits = host_state.traits

        passes = required_trait in host_traits
        if not passes:
            LOG.debug(
                "NetworkGroupAffinityFilter: host %(host)s rejected. "
                "Required trait %(trait)s not found in host traits.",
                {'host': host_state.host, 'trait': required_trait})
        return passes


class NetworkGroupAntiAffinityFilter(filters.BaseHostFilter):
    """Schedule instances onto hosts NOT within a specific network group.

    When a server group has the ``network-group-anti-affinity`` policy and
    a ``network_group`` rule, this filter rejects hosts whose reported
    traits include the matching ``CUSTOM_NETGROUP_*`` trait.

    This is useful for spreading workloads across cabinets or ensuring
    instances avoid a particular switch pair.
    """

    # The trait set of a host does not change within a single scheduling
    # request.
    run_filter_once_per_request = True

    RUN_ON_REBUILD = False

    def host_passes(self, host_state, spec_obj):
        instance_group = spec_obj.instance_group
        if not instance_group:
            return True

        policy = instance_group.policy if instance_group else None
        if policy != 'network-group-anti-affinity':
            return True

        rules = instance_group.rules
        network_group = rules.get('network_group') if rules else None
        if not network_group:
            return True

        excluded_trait = _network_group_to_trait(network_group)

        host_traits = set()
        if hasattr(host_state, 'traits'):
            host_traits = host_state.traits

        passes = excluded_trait not in host_traits
        if not passes:
            LOG.debug(
                "NetworkGroupAntiAffinityFilter: host %(host)s rejected. "
                "Excluded trait %(trait)s found in host traits.",
                {'host': host_state.host, 'trait': excluded_trait})
        return passes
