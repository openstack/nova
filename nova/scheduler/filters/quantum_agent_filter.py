# Copyright (c) 2012 OpenStack Foundation
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

from oslo.config import cfg

from nova.openstack.common import log as logging
from nova.scheduler import filters
from nova.network.quantumv2 import constants

CONF = cfg.CONF

LOG = logging.getLogger(__name__)


class QuantumAgentFilter(filters.BaseHostFilter):
    """Filter on Compute nodes with all Quantum agents alive."""

    def host_passes(self, host_state, filter_properties):
        agents_status = host_state.quantum_agents_status

        if len(agents_status) != constants.NUM_ACTIVE_AGENTS:
            LOG.warn(_("QuantumAgentFilter Not all Quantum agents "
                       "are running on %s!"), host_state.host)
            return False

        passed = True
        for agent in agents_status:
            if agent['alive'] is False:
                LOG.warn(_("QuantumAgentFilter %s is dead on %s."),
                    agent['agent_type'], host_state.host)
                passed = False
        return passed
