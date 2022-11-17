# Copyright (c) 2015 Ericsson AB
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
Affinity Weighers.  Weigh hosts by the number of instances from a given host.

AffinityWeigher implements the soft-affinity policy for server groups by
preferring the hosts that has more instances from the given group.

AntiAffinityWeigher implements the soft-anti-affinity policy for server groups
by preferring the hosts that has less instances from the given group.

"""
from oslo_config import cfg
from oslo_log import log as logging

from nova.scheduler import utils
from nova.scheduler import weights

CONF = cfg.CONF

LOG = logging.getLogger(__name__)


class _SoftAffinityWeigherBase(weights.BaseHostWeigher):
    policy_name = None

    def _weigh_object(self, host_state, request_spec):
        """Higher weights win."""
        members = self.host_info_requiring_instance_ids(request_spec)
        if not members:
            return 0

        instances = set(host_state.instances.keys())
        member_on_host = instances.intersection(members)

        return len(member_on_host)

    def host_info_requiring_instance_ids(self, request_spec):
        if not request_spec.instance_group:
            return set()

        policy = request_spec.instance_group.policy

        if self.policy_name != policy:
            return set()

        return set(request_spec.instance_group.members)


class ServerGroupSoftAffinityWeigher(_SoftAffinityWeigherBase):
    policy_name = 'soft-affinity'

    def weight_multiplier(self, host_state):
        return utils.get_weight_multiplier(
            host_state, 'soft_affinity_weight_multiplier',
            CONF.filter_scheduler.soft_affinity_weight_multiplier)


class ServerGroupSoftAntiAffinityWeigher(_SoftAffinityWeigherBase):
    policy_name = 'soft-anti-affinity'

    def weight_multiplier(self, host_state):
        return utils.get_weight_multiplier(
            host_state, 'soft_anti_affinity_weight_multiplier',
            CONF.filter_scheduler.soft_anti_affinity_weight_multiplier)

    def _weigh_object(self, host_state, request_spec):
        weight = super(ServerGroupSoftAntiAffinityWeigher, self)._weigh_object(
            host_state, request_spec)
        return -1 * weight
