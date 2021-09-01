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

mdev_opts = [
    cfg.ListOpt('enabled_mdev_types',
        default=[],
        deprecated_name='enabled_vgpu_types',
        help="""
The mdev types enabled in the compute node.

Some hardware (e.g. NVIDIA GRID K1) support different mdev types. User can use
this option to specify a list of enabled mdev types that may be assigned to a
guest instance.

If more than one single mdev type is provided, then for each *mdev type* an
additional section, ``[mdev_$(MDEV_TYPE)]``, must be added to the configuration
file. Each section then **must** be configured with a single configuration
option, ``device_addresses``, which should be a list of PCI addresses
corresponding to the physical GPU(s) or mdev-capable hardware to assign to this
type.

If one or more sections are missing (meaning that a specific type is not wanted
to use for at least one physical device) or if no device addresses are provided
, then Nova will only use the first type that was provided by
``[devices]/enabled_mdev_types``.

If the same PCI address is provided for two different types, nova-compute will
return an InvalidLibvirtMdevConfig exception at restart.

As an interim period, old configuration groups named ``[vgpu_$(MDEV_TYPE)]``
will be accepted. A valid configuration could then be::

    [devices]
    enabled_mdev_types = nvidia-35, nvidia-36

    [mdev_nvidia-35]
    device_addresses = 0000:84:00.0,0000:85:00.0

    [vgpu_nvidia-36]
    device_addresses = 0000:86:00.0

""")
]


def register_opts(conf):
    conf.register_group(devices_group)
    conf.register_opts(mdev_opts, group=devices_group)


def register_dynamic_opts(conf):
    """Register dynamically-generated options and groups.

    This must be called by the service that wishes to use the options **after**
    the initial configuration has been loaded.
    """

    for mdev_type in conf.devices.enabled_mdev_types:
        # Register the '[mdev_$(MDEV_TYPE)]/device_addresses' opts, implicitly
        # registering the '[mdev_$(MDEV_TYPE)]' groups in the process
        opt = cfg.ListOpt('device_addresses', default=[],
                          item_type=cfg.types.String(),
                          deprecated_group='vgpu_%s' % mdev_type)
        conf.register_opt(opt, group='mdev_%s' % mdev_type)

        # Register the '[mdev_$(MDEV_TYPE)]/mdev_class' opts
        class_opt = cfg.StrOpt(
            'mdev_class',
            default='VGPU',
            regex=r'^(VGPU|CUSTOM_[A-Z0-9_]+)$',
            max_length=255,
            help='Class of mediated device to manage used to differentiate '
                 'between device types. The name has to be prefixed by '
                 'CUSTOM_ if it is not VGPU.')
        conf.register_opt(class_opt, group='mdev_%s' % mdev_type)


def list_opts():
    return {devices_group: mdev_opts}
