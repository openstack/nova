# Copyright (c) 2016 TUBITAK BILGEM
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

from oslo_config import cfg

hyperv_opt_group = cfg.OptGroup("hyperv",
    title='The Hyper-V feature',
    help="""
The hyperv feature allows you to configure the Hyper-V hypervisor
driver to be used within an OpenStack deployment.
""")

hyperv_opts = [
    cfg.FloatOpt('dynamic_memory_ratio',
        default=1.0,
        help="""
Dynamic memory ratio

Enables dynamic memory allocation (ballooning) when set to a value
greater than 1. The value expresses the ratio between the total RAM
assigned to an instance and its startup RAM amount. For example a
ratio of 2.0 for an instance with 1024MB of RAM implies 512MB of
RAM allocated at startup.

Possible values:

* 1.0: Disables dynamic memory allocation (Default).
* Float values greater than 1.0: Enables allocation of total implied
  RAM divided by this value for startup.
"""),
    cfg.BoolOpt('enable_instance_metrics_collection',
        default=False,
        help="""
Enable instance metrics collection

Enables metrics collections for an instance by using Hyper-V's
metric APIs. Collected data can be retrieved by other apps and
services, e.g.: Ceilometer.
"""),
    cfg.StrOpt('instances_path_share',
        default="",
        help="""
Instances path share

The name of a Windows share mapped to the "instances_path" dir
and used by the resize feature to copy files to the target host.
If left blank, an administrative share (hidden network share) will
be used, looking for the same "instances_path" used locally.

Possible values:

* "": An administrative share will be used (Default).
* Name of a Windows share.

Related options:

* "instances_path": The directory which will be used if this option
  here is left blank.
"""),
    cfg.BoolOpt('limit_cpu_features',
        default=False,
        help="""
Limit CPU features

This flag is needed to support live migration to hosts with
different CPU features and checked during instance creation
in order to limit the CPU features used by the instance.
"""),
    cfg.IntOpt('mounted_disk_query_retry_count',
        default=10,
        min=0,
        help="""
Mounted disk query retry count

The number of times to retry checking for a mounted disk.
The query runs until the device can be found or the retry
count is reached.

Possible values:

* Positive integer values. Values greater than 1 is recommended
  (Default: 10).

Related options:

* Time interval between disk mount retries is declared with
  "mounted_disk_query_retry_interval" option.
"""),
    cfg.IntOpt('mounted_disk_query_retry_interval',
        default=5,
        min=0,
        help="""
Mounted disk query retry interval

Interval between checks for a mounted disk, in seconds.

Possible values:

* Time in seconds (Default: 5).

Related options:

* This option is meaningful when the mounted_disk_query_retry_count
  is greater than 1.
* The retry loop runs with mounted_disk_query_retry_count and
  mounted_disk_query_retry_interval configuration options.
"""),
    cfg.IntOpt('power_state_check_timeframe',
        default=60,
        min=0,
        help="""
Power state check timeframe

The timeframe to be checked for instance power state changes.
This option is used to fetch the state of the instance from Hyper-V
through the WMI interface, within the specified timeframe.

Possible values:

* Timeframe in seconds (Default: 60).
"""),
    cfg.IntOpt('power_state_event_polling_interval',
        default=2,
        min=0,
        help="""
Power state event polling interval

Instance power state change event polling frequency. Sets the
listener interval for power state events to the given value.
This option enhances the internal lifecycle notifications of
instances that reboot themselves. It is unlikely that an operator
has to change this value.

Possible values:

* Time in seconds (Default: 2).
"""),
    cfg.StrOpt('qemu_img_cmd',
        default="qemu-img.exe",
        help=r"""
qemu-img command

qemu-img is required for some of the image related operations
like converting between different image types. You can get it
from here: (http://qemu.weilnetz.de/) or you can install the
Cloudbase OpenStack Hyper-V Compute Driver
(https://cloudbase.it/openstack-hyperv-driver/) which automatically
sets the proper path for this config option. You can either give the
full path of qemu-img.exe or set its path in the PATH environment
variable and leave this option to the default value.

Possible values:

* Name of the qemu-img executable, in case it is in the same
  directory as the nova-compute service or its path is in the
  PATH environment variable (Default).
* Path of qemu-img command (DRIVELETTER:\PATH\TO\QEMU-IMG\COMMAND).

Related options:

* If the config_drive_cdrom option is False, qemu-img will be used to
  convert the ISO to a VHD, otherwise the config drive will
  remain an ISO. To use config drive with Hyper-V, you must
  set the ``mkisofs_cmd`` value to the full path to an ``mkisofs.exe``
  installation.
"""),
    cfg.StrOpt('vswitch_name',
        help="""
External virtual switch name

The Hyper-V Virtual Switch is a software-based layer-2 Ethernet
network switch that is available with the installation of the
Hyper-V server role. The switch includes programmatically managed
and extensible capabilities to connect virtual machines to both
virtual networks and the physical network. In addition, Hyper-V
Virtual Switch provides policy enforcement for security, isolation,
and service levels. The vSwitch represented by this config option
must be an external one (not internal or private).

Possible values:

* If not provided, the first of a list of available vswitches
  is used. This list is queried using WQL.
* Virtual switch name.
"""),
    cfg.IntOpt('wait_soft_reboot_seconds',
        default=60,
        min=0,
        help="""
Wait soft reboot seconds

Number of seconds to wait for instance to shut down after soft
reboot request is made. We fall back to hard reboot if instance
does not shutdown within this window.

Possible values:

* Time in seconds (Default: 60).
"""),
    cfg.BoolOpt('config_drive_cdrom',
        default=False,
        help="""
Mount config drive as a CD drive.

OpenStack can be configured to write instance metadata to a config drive, which
is then attached to the instance before it boots. The config drive can be
attached as a disk drive (default) or as a CD drive.

Related options:

* This option is meaningful with ``force_config_drive`` option set to ``True``
  or when the REST API call to create an instance will have
  ``--config-drive=True`` flag.
* ``config_drive_format`` option must be set to ``iso9660`` in order to use
  CD drive as the config drive image.
* To use config drive with Hyper-V, you must set the
  ``mkisofs_cmd`` value to the full path to an ``mkisofs.exe`` installation.
  Additionally, you must set the ``qemu_img_cmd`` value to the full path
  to an ``qemu-img`` command installation.
* You can configure the Compute service to always create a configuration
  drive by setting the ``force_config_drive`` option to ``True``.
"""),
    cfg.BoolOpt('config_drive_inject_password',
        default=False,
        help="""
Inject password to config drive.

When enabled, the admin password will be available from the config drive image.

Related options:

* This option is meaningful when used with other options that enable
  config drive usage with Hyper-V, such as ``force_config_drive``.
"""),
    cfg.IntOpt('volume_attach_retry_count',
        default=10,
        min=0,
        help="""
Volume attach retry count

The number of times to retry attaching a volume. Volume attachment
is retried until success or the given retry count is reached.

Possible values:

* Positive integer values (Default: 10).

Related options:

* Time interval between attachment attempts is declared with
  volume_attach_retry_interval option.
"""),
    cfg.IntOpt('volume_attach_retry_interval',
        default=5,
        min=0,
        help="""
Volume attach retry interval

Interval between volume attachment attempts, in seconds.

Possible values:

* Time in seconds (Default: 5).

Related options:

* This options is meaningful when volume_attach_retry_count
  is greater than 1.
* The retry loop runs with volume_attach_retry_count and
  volume_attach_retry_interval configuration options.
"""),
    cfg.BoolOpt('enable_remotefx',
        default=False,
        help="""
Enable RemoteFX feature

This requires at least one DirectX 11 capable graphics adapter for
Windows / Hyper-V Server 2012 R2 or newer and RDS-Virtualization
feature has to be enabled.

Instances with RemoteFX can be requested with the following flavor
extra specs:

**os:resolution**. Guest VM screen resolution size. Acceptable values::

    1024x768, 1280x1024, 1600x1200, 1920x1200, 2560x1600, 3840x2160

``3840x2160`` is only available on Windows / Hyper-V Server 2016.

**os:monitors**. Guest VM number of monitors. Acceptable values::

    [1, 4] - Windows / Hyper-V Server 2012 R2
    [1, 8] - Windows / Hyper-V Server 2016

**os:vram**. Guest VM VRAM amount. Only available on
Windows / Hyper-V Server 2016. Acceptable values::

    64, 128, 256, 512, 1024
"""),
    cfg.BoolOpt('use_multipath_io',
                default=False,
                help="""
Use multipath connections when attaching iSCSI or FC disks.

This requires the Multipath IO Windows feature to be enabled. MPIO must be
configured to claim such devices.
"""),
    cfg.ListOpt('iscsi_initiator_list',
                default=[],
                help="""
List of iSCSI initiators that will be used for estabilishing iSCSI sessions.

If none are specified, the Microsoft iSCSI initiator service will choose the
initiator.
""")
]


def register_opts(conf):
    conf.register_group(hyperv_opt_group)
    conf.register_opts(hyperv_opts, group=hyperv_opt_group)


def list_opts():
    return {hyperv_opt_group: hyperv_opts}
