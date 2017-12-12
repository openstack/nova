# Copyright 2017,2018 IBM Corp.
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

from oslo_log import log as logging

from nova.compute import power_state as compute_power_state
from nova import conf
from nova.virt import hardware


LOG = logging.getLogger(__name__)
CONF = conf.CONF


ZVM_POWER_STATE = {
    'on': compute_power_state.RUNNING,
    'off': compute_power_state.SHUTDOWN,
    }


class Guest(object):
    """z/VM implementation of ComputeDriver."""

    def __init__(self, hypervisor, instance, virtapi=None):
        super(Guest, self).__init__()

        self.virtapi = virtapi
        self._hypervisor = hypervisor
        self._instance = instance

    def _mapping_power_state(self, power_state):
        """Translate power state to OpenStack defined constants."""
        return ZVM_POWER_STATE.get(power_state, compute_power_state.NOSTATE)

    def get_info(self):
        """Get the current status of an instance."""
        power_state = self._mapping_power_state(
            self._hypervisor.guest_get_power_state(
                self._instance.name))
        return hardware.InstanceInfo(power_state)
