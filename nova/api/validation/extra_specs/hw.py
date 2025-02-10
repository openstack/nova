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

"""Validators for ``hw`` namespaced extra specs."""

from nova.api.validation.extra_specs import base
from nova.objects import fields


realtime_validators = [
    base.ExtraSpecValidator(
        name='hw:cpu_realtime',
        description=(
            'Determine whether realtime mode should be enabled for the '
            'instance or not. '
            'Only supported by the libvirt virt driver.'
        ),
        value={
            'type': bool,
            'description': 'Whether to enable realtime priority.',
        },
    ),
    base.ExtraSpecValidator(
        name='hw:cpu_realtime_mask',
        description=(
            'A exclusion mask of CPUs that should not be enabled for '
            'realtime. '
            'Only supported by the libvirt virt driver.'
        ),
        value={
            'type': str,
            'pattern': r'(\^)?\d+((-\d+)?(,\^?\d+(-\d+)?)?)*',
        },
    ),
]

hide_hypervisor_id_validator = [
    base.ExtraSpecValidator(
        name='hw:hide_hypervisor_id',
        description=(
            'Determine whether the hypervisor ID should be hidden from the '
            'guest. '
            'Only supported by the libvirt virt driver.'
        ),
        value={
            'type': bool,
            'description': 'Whether to hide the hypervisor ID.',
        },
    )
]

cpu_policy_validators = [
    base.ExtraSpecValidator(
        name='hw:cpu_policy',
        description=(
            'The policy to apply when determining what host CPUs the guest '
            'CPUs can run on. '
            'If ``shared`` (default), guest CPUs can be overallocated but '
            'cannot float across host cores. '
            'If ``dedicated``, guest CPUs cannot be overallocated but are '
            'individually pinned to their own host core. '
            'If ``mixed``, the policy for each instance CPU can be specified '
            'using the ``hw:cpu_dedicated_mask`` or ``hw:cpu_realtime_mask`` '
            'extra specs.'
            'Only supported by the libvirt virt driver.'
        ),
        value={
            'type': str,
            'description': 'The CPU policy.',
            'enum': [
                'dedicated',
                'shared',
                'mixed',
            ],
        },
    ),
    base.ExtraSpecValidator(
        name='hw:cpu_thread_policy',
        description=(
            'The policy to apply when determining whether the destination '
            'host can have hardware threads enabled or not. '
            'If ``prefer`` (default), hosts with hardware threads will be '
            'preferred. '
            'If ``require``, hosts with hardware threads will be required. '
            'If ``isolate``, hosts with hardware threads will be forbidden. '
            'Only supported by the libvirt virt driver.'
        ),
        value={
            'type': str,
            'description': 'The CPU thread policy.',
            'enum': [
                'prefer',
                'isolate',
                'require',
            ],
        },
    ),
    base.ExtraSpecValidator(
        name='hw:emulator_threads_policy',
        description=(
            'The policy to apply when determining whether emulator threads '
            'should be offloaded to a separate isolated core or to a pool '
            'of shared cores. '
            'If ``share``, emulator overhead threads will be offloaded to a '
            'pool of shared cores. '
            'If ``isolate``, emulator overhead threads will be offloaded to '
            'their own core. '
            'Only supported by the libvirt virt driver.'
        ),
        value={
            'type': str,
            'description': 'The emulator thread policy.',
            'enum': [
                'isolate',
                'share',
            ],
        },
    ),
    base.ExtraSpecValidator(
        name='hw:cpu_dedicated_mask',
        description=(
            'A mapping of **guest** (instance) CPUs to be pinned to **host** '
            'CPUs for an instance with a ``mixed`` CPU policy. '
            'Any **guest** CPUs which are not in this mapping will float '
            'across host cores. '
            'Only supported by the libvirt virt driver.'
        ),
        value={
            'type': str,
            'description': (
                'The **guest** CPU mapping to be pinned to **host** CPUs for '
                'an instance with a ``mixed`` CPU policy.'
            ),
            # This pattern is identical to 'hw:cpu_realtime_mask' pattern.
            'pattern': r'\^?\d+((-\d+)?(,\^?\d+(-\d+)?)?)*',
        },
    ),
]

hugepage_validators = [
    base.ExtraSpecValidator(
        name='hw:mem_page_size',
        description=(
            'The size of memory pages to allocate to the guest with. '
            'Can be one of the three alias - ``large``, ``small`` or '
            '``any``, - or an actual size. '
            'Only supported by the libvirt virt driver.'
        ),
        value={
            'type': str,
            'description': 'The size of memory page to allocate',
            'pattern': r'(large|small|any|\d+([kKMGT]i?)?(b|bit|B)?)',
        },
    ),
    base.ExtraSpecValidator(
        name='hw:locked_memory',
        description=(
            'Determine if **guest** (instance) memory should be locked '
            'preventing swaping. This is required in rare cases for device '
            'DMA transfers. Only supported by the libvirt virt driver.'
        ),
        value={
            'type': bool,
            'description': 'Whether to lock **guest** (instance) memory.',
        },
    ),
]

numa_validators = [
    base.ExtraSpecValidator(
        name='hw:numa_nodes',
        description=(
            'The number of virtual NUMA nodes to allocate to configure the '
            'guest with. '
            'Each virtual NUMA node will be mapped to a unique host NUMA '
            'node. '
            'Only supported by the libvirt virt driver.'
        ),
        value={
            'type': int,
            'description': 'The number of virtual NUMA nodes to allocate',
            'min': 1,
        },
    ),
    base.ExtraSpecValidator(
        name='hw:numa_cpus.{num}',
        description=(
            'A mapping of **guest** (instance) CPUs to the **guest** (not '
            'host!) NUMA node identified by ``{num}``. '
            'This can be used to provide asymmetric CPU-NUMA allocation and '
            'is necessary where the number of guest NUMA nodes is not a '
            'factor of the number of guest CPUs. '
            'Only supported by the libvirt virt driver.'
        ),
        parameters=[
            {
                'name': 'num',
                'pattern': r'\d+',  # positive integers
                'description': 'The ID of the **guest** NUMA node.',
            },
        ],
        value={
            'type': str,
            'description': (
                'The guest CPUs, in the form of a CPU map, to allocate to the '
                'guest NUMA node identified by ``{num}``.'
            ),
            'pattern': r'\^?\d+((-\d+)?(,\^?\d+(-\d+)?)?)*',
        },
    ),
    base.ExtraSpecValidator(
        name='hw:numa_mem.{num}',
        description=(
            'A mapping of **guest** memory to the **guest** (not host!) NUMA '
            'node identified by ``{num}``. '
            'This can be used to provide asymmetric memory-NUMA allocation '
            'and is necessary where the number of guest NUMA nodes is not a '
            'factor of the total guest memory. '
            'Only supported by the libvirt virt driver.'
        ),
        parameters=[
            {
                'name': 'num',
                'pattern': r'\d+',  # positive integers
                'description': 'The ID of the **guest** NUMA node.',
            },
        ],
        value={
            'type': int,
            'description': (
                'The guest memory, in MB, to allocate to the guest NUMA node '
                'identified by ``{num}``.'
            ),
            'min': 1,
        },
    ),
    base.ExtraSpecValidator(
        name='hw:pci_numa_affinity_policy',
        description=(
            'The NUMA affinity policy of any PCI passthrough devices or '
            'SR-IOV network interfaces attached to the instance. '
            'If ``required`, only PCI devices from one of the host NUMA '
            'nodes the instance VCPUs are allocated from can be used by said '
            'instance. '
            'If ``preferred``, any PCI device can be used, though preference '
            'will be given to those from the same NUMA node as the instance '
            'VCPUs. '
            'If ``legacy`` (default), behavior is as with ``required`` unless '
            'the PCI device does not support provide NUMA affinity '
            'information, in which case affinity is ignored. '
            'Only supported by the libvirt virt driver.'
        ),
        value={
            'type': str,
            'description': 'The PCI NUMA affinity policy',
            'enum': [
                'required',
                'preferred',
                'legacy',
                'socket',
            ],
        },
    ),
]

cpu_topology_validators = [
    base.ExtraSpecValidator(
        name='hw:cpu_sockets',
        description=(
            'The number of virtual CPU threads to emulate in the guest '
            'CPU topology. '
            'Defaults to the number of vCPUs requested. '
            'Only supported by the libvirt virt driver.'
        ),
        value={
            'type': int,
            'description': 'A number of virtual CPU sockets',
            'min': 1,
        },
    ),
    base.ExtraSpecValidator(
        name='hw:cpu_cores',
        description=(
            'The number of virtual CPU cores to emulate per socket in the '
            'guest CPU topology. '
            'Defaults to ``1``.'
            'Only supported by the libvirt virt driver. '
        ),
        value={
            'type': int,
            'description': 'A number of virtual CPU cores',
            'min': 1,
        },
    ),
    base.ExtraSpecValidator(
        name='hw:cpu_threads',
        description=(
            'The number of virtual CPU threads to emulate per core in the '
            'guest CPU topology.'
            'Defaults to ``1``. '
            'Only supported by the libvirt virt driver. '
        ),
        value={
            'type': int,
            'description': 'A number of virtual CPU threads',
            'min': 1,
        },
    ),
    base.ExtraSpecValidator(
        name='hw:max_cpu_sockets',
        description=(
            'The max number of virtual CPU threads to emulate in the '
            'guest CPU topology. '
            'This is used to limit the topologies that can be requested by '
            'an image and will be used to validate the ``hw_cpu_sockets`` '
            'image metadata property. '
            'Only supported by the libvirt virt driver. '
        ),
        value={
            'type': int,
            'description': 'A number of virtual CPU sockets',
            'min': 1,
        },
    ),
    base.ExtraSpecValidator(
        name='hw:max_cpu_cores',
        description=(
            'The max number of virtual CPU cores to emulate per socket in the '
            'guest CPU topology. '
            'This is used to limit the topologies that can be requested by an '
            'image and will be used to validate the ``hw_cpu_cores`` image '
            'metadata property. '
            'Only supported by the libvirt virt driver. '
        ),
        value={
            'type': int,
            'description': 'A number of virtual CPU cores',
            'min': 1,
        },
    ),
    base.ExtraSpecValidator(
        name='hw:max_cpu_threads',
        description=(
            'The max number of virtual CPU threads to emulate per core in the '
            'guest CPU topology. '
            'This is used to limit the topologies that can be requested by an '
            'image and will be used to validate the ``hw_cpu_threads`` image '
            'metadata property. '
            'Only supported by the libvirt virt driver. '
        ),
        value={
            'type': int,
            'description': 'A number of virtual CPU threads',
            'min': 1,
        },
    ),
]

feature_flag_validators = [
    # TODO(stephenfin): Consider deprecating and moving this to the 'os:'
    # namespace
    base.ExtraSpecValidator(
        name='hw:boot_menu',
        description=(
            'Whether to show a boot menu when booting the guest. '
            'Only supported by the libvirt virt driver. '
        ),
        value={
            'type': bool,
            'description': 'Whether to enable the boot menu',
        },
    ),
    base.ExtraSpecValidator(
        name='hw:vif_multiqueue_enabled',
        description=(
            'Whether to enable the virtio-net multiqueue feature. '
            'When set, the driver sets the number of queues equal to the '
            'number of guest vCPUs. This makes the network performance scale '
            'across a number of vCPUs. This requires guest support and is '
            'only supported by the libvirt driver.'
        ),
        value={
            'type': bool,
            'description': 'Whether to enable multiqueue',
        },
    ),
    base.ExtraSpecValidator(
        name='hw:mem_encryption',
        description=(
            'Whether to enable memory encryption for the guest. '
            'Only supported by the libvirt virt driver on hosts with AMD SEV '
            'support.'
        ),
        value={
            'type': bool,
            'description': 'Whether to enable memory encryption',
        },
    ),
    base.ExtraSpecValidator(
        name='hw:pmem',
        description=(
            'A comma-separated list of ``$LABEL``\\ s defined in config for '
            'vPMEM devices. '
            'Only supported by the libvirt virt driver on hosts with PMEM '
            'devices.'
        ),
        value={
            'type': str,
            'description': (
                'A comma-separated list of valid resource class names.'
            ),
            'pattern': '([a-zA-Z0-9_]+(,)?)+',
        },
    ),
    base.ExtraSpecValidator(
        name='hw:pmu',
        description=(
            'Whether to enable the Performance Monitory Unit (PMU) for the '
            'guest. '
            'If this option is not specified, the presence of the vPMU is '
            'determined by the hypervisor. '
            'The vPMU is used by tools like ``perf`` in the guest to provide '
            'more accurate information for profiling application and '
            'monitoring guest performance. '
            'For realtime workloads, the emulation of a vPMU can introduce '
            'additional latency which may be undesirable. '
            'If the telemetry it provides is not required, such workloads '
            'should disable this feature. '
            'For most workloads, the default of unset will be correct. '
            'Only supported by the libvirt virt driver.'
        ),
        value={
            'type': bool,
            'description': 'Whether to enable the PMU',
        },
    ),
    base.ExtraSpecValidator(
        name='hw:serial_port_count',
        description=(
            'The number of serial ports to allocate to the guest. '
            'Only supported by the libvirt virt driver.'
        ),
        value={
            'type': int,
            'min': 0,
            'description': 'The number of serial ports to allocate',
        },
    ),
    base.ExtraSpecValidator(
        name='hw:tpm_model',
        description=(
            'The model of the attached TPM device. '
            'Only supported by the libvirt virt driver.'
        ),
        value={
            'type': str,
            'description': 'A TPM model',
            'enum': [
                'tpm-tis',
                'tpm-crb',
            ],
        },
    ),
    base.ExtraSpecValidator(
        name='hw:tpm_version',
        description=(
            "The TPM version. "
            "Required if requesting a vTPM via the 'hw:tpm_model' extra spec "
            "or equivalent image metadata property. "
            "Only supported by the libvirt virt driver."
        ),
        value={
            'type': str,
            'description': 'A TPM version.',
            'enum': [
                '1.2',
                '2.0',
            ],
        },
    ),
    base.ExtraSpecValidator(
        name='hw:watchdog_action',
        description=(
            'The action to take when the watchdog timer is kicked. '
            'Watchdog devices keep an eye on the instance and carry out the '
            'specified action if the server hangs. '
            'The watchdog uses the ``i6300esb`` device, emulating a PCI Intel '
            '6300ESB. '
            'Only supported by the libvirt virt driver.'
        ),
        value={
            'type': str,
            'description': 'The action to take',
            'enum': [
                'none',
                'pause',
                'poweroff',
                'reset',
                'disabled',
            ],
        },
    ),
    base.ExtraSpecValidator(
        name='hw:viommu_model',
        description=(
            'This can be used to set model for virtual IOMMU device.'
        ),
        value={
            'type': str,
            'enum': [
                'intel',
                'smmuv3',
                'virtio',
                'auto'
            ],
            'description': 'model for vIOMMU',
        },
    ),
    base.ExtraSpecValidator(
        name='hw:virtio_packed_ring',
        description=(
            'Permit guests to negotiate the virtio packed ring format. '
            'This requires guest support and is only supported by '
            'the libvirt driver.'
        ),
        value={
            'type': bool,
            'description': 'Whether to enable packed virtqueue',
        },
    ),
]

ephemeral_encryption_validators = [
    base.ExtraSpecValidator(
        name='hw:ephemeral_encryption',
        description=(
            'Whether to enable ephemeral storage encryption.'
        ),
        value={
            'type': bool,
            'description': 'Whether to enable ephemeral storage encryption.',
        },
    ),
    base.ExtraSpecValidator(
        name='hw:ephemeral_encryption_format',
        description=(
            'The encryption format to be used if ephemeral storage '
            'encryption is enabled via hw:ephemeral_encryption.'
        ),
        value={
            'type': str,
            'description': 'The encryption format to be used if enabled.',
            'enum': fields.BlockDeviceEncryptionFormatType.ALL,
        },
    ),
]


def register():
    return (
        realtime_validators +
        hide_hypervisor_id_validator +
        cpu_policy_validators +
        hugepage_validators +
        numa_validators +
        cpu_topology_validators +
        feature_flag_validators +
        ephemeral_encryption_validators
    )
