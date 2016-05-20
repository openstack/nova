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
                title="The Hyper-V feature",
                help="""
The hyperv feature allows you to configure the Hyper-V hypervisor
driver to be used within an OpenStack deployment.
""")


dynamic_memory_ratio_opt = cfg.FloatOpt('dynamic_memory_ratio',
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

Services which consume this:

* nova-compute

Related options:

* None
""")

enable_instance_metrics_collection_opt = cfg.BoolOpt(
                'enable_instance_metrics_collection',
                default=False,
                help="""
Enable instance metrics collection

Enables metrics collections for an instance by using Hyper-V's
metric APIs. Collected data can by retrieved by other apps and
services, e.g.: Ceilometer.

Possible values:

* True: Enables metrics collection.
* False: Disables metric collection (Default).

Services which consume this:

* nova-compute

Related options:

* None
""")

instances_path_share_opt = cfg.StrOpt('instances_path_share',
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

Services which consume this:

* nova-compute

Related options:

* "instances_path": The directory which will be used if this option
  here is left blank.
""")

limit_cpu_features_opt = cfg.BoolOpt('limit_cpu_features',
                default=False,
                help="""
Limit CPU features

This flag is needed to support live migration to hosts with
different CPU features and checked during instance creation
in order to limit the CPU features used by the instance.

Possible values:

* True: Limit processor-specific features.
* False: Do not limit processor-specific features (Default).

Services which consume this:

* nova-compute

Related options:

* None
""")

mounted_disk_query_retry_count_opt = cfg.IntOpt(
                'mounted_disk_query_retry_count',
                default=10,
                help="""
Mounted disk query retry count

The number of times to retry checking for a disk mounted via iSCSI.
During long stress runs the WMI query that is looking for the iSCSI
device number can incorrectly return no data. If the query is
retried the appropriate data can then be obtained. The query runs
until the device can be found or the retry count is reached.

Possible values:

* Positive integer values. Values greater than 1 is recommended
  (Default: 10).

Services which consume this:

* nova-compute

Related options:

* Time interval between disk mount retries is declared with
  "mounted_disk_query_retry_interval" option.
""")

mounted_disk_query_retry_interval_opt = cfg.IntOpt(
                'mounted_disk_query_retry_interval',
                default=5,
                help="""
Mounted disk query retry interval

Interval between checks for a mounted iSCSI disk, in seconds.

Possible values:

* Time in seconds (Default: 5).

Services which consume this:

* nova-compute

Related options:

* This option is meaningful when the mounted_disk_query_retry_count
  is greater than 1.
* The retry loop runs with mounted_disk_query_retry_count and
  mounted_disk_query_retry_interval configuration options.
""")

power_state_check_timeframe_opt = cfg.IntOpt('power_state_check_timeframe',
                default=60,
                help="""
Power state check timeframe

The timeframe to be checked for instance power state changes.
This option is used to fetch the state of the instance from Hyper-V
through the WMI interface, within the specified timeframe.

Possible values:

* Timeframe in seconds (Default: 60).

Services which consume this:

* nova-compute

Related options:

* None
""")

power_state_event_polling_interval_opt = cfg.IntOpt(
                'power_state_event_polling_interval',
                default=2,
                help="""
Power state event polling interval

Instance power state change event polling frequency. Sets the
listener interval for power state events to the given value.
This option enhances the internal lifecycle notifications of
instances that reboot themselves. It is unlikely that an operator
has to change this value.

Possible values:

* Time in seconds (Default: 2).

Services which consume this:

* nova-compute

Related options:

* None
""")

qemu_img_cmd_opt = cfg.StrOpt('qemu_img_cmd',
                default="qemu-img.exe",
                help="""
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

Services which consume this:

* nova-compute

Related options:

* If the config_drive_cdrom option is False, qemu-img will be used to
  convert the ISO to a VHD, otherwise the configuration drive will
  remain an ISO. To use configuration drive with Hyper-V, you must
  set the mkisofs_cmd value to the full path to an mkisofs.exe
  installation.
""")

vswitch_name_opt = cfg.StrOpt('vswitch_name',
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

Services which consume this:

* nova-compute

Related options:

* None
""")

wait_soft_reboot_seconds_opt = cfg.IntOpt('wait_soft_reboot_seconds',
                default=60,
                help="""
Wait soft reboot seconds

Number of seconds to wait for instance to shut down after soft
reboot request is made. We fall back to hard reboot if instance
does not shutdown within this window.

Possible values:

* Time in seconds (Default: 60).

Services which consume this:

* nova-compute

Related options:

* None
""")

config_drive_cdrom_opt = cfg.BoolOpt('config_drive_cdrom',
                default=False,
                help="""
Configuration drive cdrom

OpenStack can be configured to write instance metadata to
a configuration drive, which is then attached to the
instance before it boots. The configuration drive can be
attached as a disk drive (default) or as a CD drive.

Possible values:

* True: Attach the configuration drive image as a CD drive.
* False: Attach the configuration drive image as a disk drive (Default).

Services which consume this:

* nova-compute

Related options:

* This option is meaningful with force_config_drive option set to 'True'
  or when the REST API call to create an instance will have
  '--config-drive=True' flag.
* config_drive_format option must be set to 'iso9660' in order to use
  CD drive as the configuration drive image.
* To use configuration drive with Hyper-V, you must set the
  mkisofs_cmd value to the full path to an mkisofs.exe installation.
  Additionally, you must set the qemu_img_cmd value to the full path
  to an qemu-img command installation.
* You can configure the Compute service to always create a configuration
  drive by setting the force_config_drive option to 'True'.
""")

config_drive_inject_password_opt = cfg.BoolOpt('config_drive_inject_password',
                default=False,
                help="""
Configuration drive inject password

Enables setting the admin password in the configuration drive image.

Possible values:

* True: Enables the feature.
* False: Disables the feature (Default).

Services which consume this:

* nova-compute

Related options:

* This option is meaningful when used with other options that enable
  configuration drive usage with Hyper-V, such as force_config_drive.
* Currently, the only accepted config_drive_format is 'iso9660'.
""")

volume_attach_retry_count_opt = cfg.IntOpt('volume_attach_retry_count',
                default=10,
                help="""
Volume attach retry count

The number of times to retry to attach a volume. This option is used
to avoid incorrectly returned no data when the system is under load.
Volume attachment is retried until success or the given retry count
is reached. To prepare the Hyper-V node to be able to attach to
volumes provided by cinder you must first make sure the Windows iSCSI
initiator service is running and started automatically.

Possible values:

* Positive integer values (Default: 10).

Services which consume this:

* nova-compute

Related options:

* Time interval between attachment attempts is declared with
  volume_attach_retry_interval option.
""")

volume_attach_retry_interval_opt = cfg.IntOpt('volume_attach_retry_interval',
                default=5,
                help="""
Volume attach retry interval

Interval between volume attachment attempts, in seconds.

Possible values:

* Time in seconds (Default: 5).

Services which consume this:

* nova-compute

Related options:

* This options is meaningful when volume_attach_retry_count
  is greater than 1.
* The retry loop runs with volume_attach_retry_count and
  volume_attach_retry_interval configuration options.
""")


ALL_OPTS = [dynamic_memory_ratio_opt,
            enable_instance_metrics_collection_opt,
            instances_path_share_opt,
            limit_cpu_features_opt,
            mounted_disk_query_retry_count_opt,
            mounted_disk_query_retry_interval_opt,
            power_state_check_timeframe_opt,
            power_state_event_polling_interval_opt,
            qemu_img_cmd_opt,
            vswitch_name_opt,
            wait_soft_reboot_seconds_opt,
            config_drive_cdrom_opt,
            config_drive_inject_password_opt,
            volume_attach_retry_count_opt,
            volume_attach_retry_interval_opt]


def register_opts(conf):
    conf.register_opts(ALL_OPTS, group=hyperv_opt_group)


def list_opts():
    return {hyperv_opt_group: ALL_OPTS}
