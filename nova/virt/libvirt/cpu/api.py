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

from dataclasses import dataclass

from oslo_log import log as logging

import nova.conf
from nova.virt.libvirt.cpu import core

LOG = logging.getLogger(__name__)

CONF = nova.conf.CONF


@dataclass
class Core:
    """Class to model a CPU core as reported by sysfs.

    It may be a physical CPU core or a hardware thread on a shared CPU core
    depending on if the system supports SMT.
    """

    # NOTE(sbauza): ident is a mandatory field.
    # The CPU core id/number
    ident: int

    @property
    def online(self) -> bool:
        return core.get_online(self.ident)

    @online.setter
    def online(self, state: bool) -> None:
        if state:
            core.set_online(self.ident)
        else:
            core.set_offline(self.ident)

    def __hash__(self):
        return hash(self.ident)

    def __eq__(self, other):
        return self.ident == other.ident

    @property
    def governor(self) -> str:
        return core.get_governor(self.ident)

    def set_high_governor(self) -> None:
        core.set_governor(self.ident, CONF.libvirt.cpu_power_governor_high)

    def set_low_governor(self) -> None:
        core.set_governor(self.ident, CONF.libvirt.cpu_power_governor_low)
