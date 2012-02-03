# Copyright (c) 2011 Openstack, LLC.
# Copyright (c) 2012 Cloudscaling
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

from nova import flags
from nova import log as logging
from nova.openstack.common import cfg
from nova.scheduler.filters import abstract_filter

LOG = logging.getLogger('nova.scheduler.filter.ram_filter')

ram_allocation_ratio_opt = cfg.FloatOpt("ram_allocation_ratio",
        default=1.0,
        help="virtual ram to physical ram allocation ratio")

FLAGS = flags.FLAGS
FLAGS.register_opt(ram_allocation_ratio_opt)


class RamFilter(abstract_filter.AbstractHostFilter):
    """Ram Filter with over subscription flag"""

    def host_passes(self, host_state, filter_properties):
        """Only return hosts with sufficient available RAM."""
        instance_type = filter_properties.get('instance_type')
        requested_ram = instance_type['memory_mb']
        free_ram_mb = host_state.free_ram_mb
        return free_ram_mb * FLAGS.ram_allocation_ratio >= requested_ram
