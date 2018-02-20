# Copyright 2014, 2017 IBM Corp.
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

import math

from oslo_serialization import jsonutils

from nova import conf as cfg
from nova.objects import fields


CONF = cfg.CONF

# Power VM hypervisor info
# Normally, the hypervisor version is a string in the form of '8.0.0' and
# converted to an int with nova.virt.utils.convert_version_to_int() however
# there isn't currently a mechanism to retrieve the exact version.
# Complicating this is the fact that nova conductor only allows live migration
# from the source host to the destination if the source is equal to or less
# than the destination version.  PowerVM live migration limitations are
# checked by the PowerVM capabilities flags and not specific version levels.
# For that reason, we'll just publish the major level.
IBM_POWERVM_HYPERVISOR_VERSION = 8

# The types of LPARS that are supported.
POWERVM_SUPPORTED_INSTANCES = [
    (fields.Architecture.PPC64, fields.HVType.PHYP, fields.VMMode.HVM),
    (fields.Architecture.PPC64LE, fields.HVType.PHYP, fields.VMMode.HVM)]


def build_host_resource_from_ms(ms_w):
    """Build the host resource dict from a ManagedSystem PowerVM wrapper.

    :param ms_w: The pypowervm System wrapper describing the managed system.
    """
    data = {}
    # Calculate the vcpus
    proc_units = ms_w.proc_units_configurable
    pu_used = float(proc_units) - float(ms_w.proc_units_avail)
    data['vcpus'] = int(math.ceil(float(proc_units)))
    data['vcpus_used'] = int(math.ceil(pu_used))
    data['memory_mb'] = ms_w.memory_configurable
    data['memory_mb_used'] = (ms_w.memory_configurable -
                              ms_w.memory_free)
    data["hypervisor_type"] = fields.HVType.PHYP
    data["hypervisor_version"] = IBM_POWERVM_HYPERVISOR_VERSION
    data["hypervisor_hostname"] = CONF.host
    data["cpu_info"] = jsonutils.dumps({'vendor': 'ibm', 'arch': 'ppc64'})
    data["numa_topology"] = None
    data["supported_instances"] = POWERVM_SUPPORTED_INSTANCES
    stats = {'proc_units': '%.2f' % float(proc_units),
             'proc_units_used': '%.2f' % pu_used,
             'memory_region_size': ms_w.memory_region_size}
    data["stats"] = stats
    return data
