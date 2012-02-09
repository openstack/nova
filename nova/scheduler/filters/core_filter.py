# Copyright (c) 2011 Openstack, LLC.
# Copyright (c) 2012 Justin Santa Barbara
#
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


LOG = logging.getLogger('nova.scheduler.filter.core_filter')

cpu_allocation_ratio_opt = cfg.FloatOpt('cpu_allocation_ratio',
        default=16.0,
        help='Virtual CPU to Physical CPU allocation ratio')

FLAGS = flags.FLAGS
FLAGS.add_option(cpu_allocation_ratio_opt)


class CoreFilter(abstract_filter.AbstractHostFilter):
    """CoreFilter filters based on CPU core utilization."""

    def host_passes(self, host_state, filter_properties):
        """Return True if host has sufficient CPU cores."""
        instance_type = filter_properties.get('instance_type')
        if host_state.topic != 'compute' or not instance_type:
            return True

        if not host_state.vcpus_total:
            # Fail safe
            LOG.warning(_("VCPUs not set; assuming CPU collection broken"))
            return True

        instance_vcpus = instance_type['vcpus']
        vcpus_total = host_state.vcpus_total * FLAGS.cpu_allocation_ratio
        return (vcpus_total - host_state.vcpus_used) >= instance_vcpus
