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

from oslo_config import cfg

devices_group = cfg.OptGroup(
    name='devices',
    title='physical or virtual device options')

vgpu_opts = [
    cfg.ListOpt('enabled_vgpu_types',
        default=[],
        help="""
The vGPU types enabled in the compute node.

Some pGPUs (e.g. NVIDIA GRID K1) support different vGPU types. User can use
this option to specify a list of enabled vGPU types that may be assigned to a
guest instance.

If more than one single vGPU type is provided, then for each *vGPU type* an
additional section, ``[vgpu_$(VGPU_TYPE)]``, must be added to the configuration
file. Each section then **must** be configured with a single configuration
option, ``device_addresses``, which should be a list of PCI addresses
corresponding to the physical GPU(s) to assign to this type.

If one or more sections are missing (meaning that a specific type is not wanted
to use for at least one physical GPU) or if no device addresses are provided,
then Nova will only use the first type that was provided by
``[devices]/enabled_vgpu_types``.

If the same PCI address is provided for two different types, nova-compute will
return an InvalidLibvirtGPUConfig exception at restart.

An example is as the following::

    [devices]
    enabled_vgpu_types = nvidia-35, nvidia-36

    [vgpu_nvidia-35]
    device_addresses = 0000:84:00.0,0000:85:00.0

    [vgpu_nvidia-36]
    device_addresses = 0000:86:00.0

""")
]


def register_opts(conf):
    conf.register_group(devices_group)
    conf.register_opts(vgpu_opts, group=devices_group)


def register_dynamic_opts(conf):
    """Register dynamically-generated options and groups.

    This must be called by the service that wishes to use the options **after**
    the initial configuration has been loaded.
    """
    opt = cfg.ListOpt('device_addresses', default=[],
                      item_type=cfg.types.String())

    # Register the '[vgpu_$(VGPU_TYPE)]/device_addresses' opts, implicitly
    # registering the '[vgpu_$(VGPU_TYPE)]' groups in the process
    for vgpu_type in conf.devices.enabled_vgpu_types:
        conf.register_opt(opt, group='vgpu_%s' % vgpu_type)


def list_opts():
    return {devices_group: vgpu_opts}
