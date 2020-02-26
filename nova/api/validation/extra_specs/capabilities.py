# Copyright 2020 Red Hat, Inc. All rights reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Validators for (preferrably) ``capabilities`` namespaced extra specs.

These are used by the ``ComputeCapabilitiesFilter`` scheduler filter. Note that
we explicitly do not allow the unnamespaced variant of extra specs since this
has been deprecated since Grizzly (commit 8ce8e4b6c0d). Users that insist on
using these can disable extra spec validation.

For all extra specs, the value can be one of the following:

* ``=`` (equal to or greater than as a number; same as vcpus case)
* ``==`` (equal to as a number)
* ``!=`` (not equal to as a number)
* ``>=`` (greater than or equal to as a number)
* ``<=`` (less than or equal to as a number)
* ``s==`` (equal to as a string)
* ``s!=`` (not equal to as a string)
* ``s>=`` (greater than or equal to as a string)
* ``s>`` (greater than as a string)
* ``s<=`` (less than or equal to as a string)
* ``s<`` (less than as a string)
* ``<in>`` (substring)
* ``<all-in>`` (all elements contained in collection)
* ``<or>`` (find one of these)
* A specific value, e.g. ``true``, ``123``, ``testing``

Examples are: ``>= 5``, ``s== 2.1.0``, ``<in> gcc``, ``<all-in> aes mmx``, and
``<or> fpu <or> gpu``
"""

from nova.api.validation.extra_specs import base


DESCRIPTION = """\
Specify that the '{capability}' capability provided by the host compute service
satisfy the provided filter value. Requires the ``ComputeCapabilitiesFilter``
scheduler filter.
"""

EXTRA_SPEC_VALIDATORS = []

# non-nested capabilities (from 'nova.objects.compute_node.ComputeNode' and
# nova.scheduler.host_manager.HostState')

for capability in (
    'id', 'uuid', 'service_id', 'host', 'vcpus', 'memory_mb', 'local_gb',
    'vcpus_used', 'memory_mb_used', 'local_gb_used',
    'hypervisor_type', 'hypervisor_version', 'hypervisor_hostname',
    'free_ram_mb', 'free_disk_gb', 'current_workload', 'running_vms',
    'disk_available_least', 'host_ip', 'mapped',
    'cpu_allocation_ratio', 'ram_allocation_ratio', 'disk_allocation_ratio',
) + (
    'total_usable_ram_mb', 'total_usable_disk_gb', 'disk_mb_used',
    'free_disk_mb', 'vcpus_total', 'vcpus_used', 'num_instances',
    'num_io_ops', 'failed_builds', 'aggregates', 'cell_uuid', 'updated',
):
    EXTRA_SPEC_VALIDATORS.append(
        base.ExtraSpecValidator(
            name=f'capabilities:{capability}',
            description=DESCRIPTION.format(capability=capability),
            value={
                # this is totally arbitary, since we need to support specific
                # values
                'type': str,
            },
        ),
    )


# nested capabilities (from 'nova.objects.compute_node.ComputeNode' and
# nova.scheduler.host_manager.HostState')

for capability in (
    'cpu_info', 'metrics', 'stats', 'numa_topology', 'supported_hv_specs',
    'pci_device_pools',
) + (
    'nodename', 'pci_stats', 'supported_instances', 'limits', 'instances',
):
    EXTRA_SPEC_VALIDATORS.extend([
        base.ExtraSpecValidator(
            name=f'capabilities:{capability}{{filter}}',
            description=DESCRIPTION.format(capability=capability),
            parameters=[
                {
                    'name': 'filter',
                    # this is optional, but if it's present it must be preceded
                    # by ':'
                    'pattern': r'(:\w+)*',
                }
            ],
            value={
                'type': str,
            },
        ),
    ])


def register():
    return EXTRA_SPEC_VALIDATORS
