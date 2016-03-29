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
The hyperv feature allows you to configure
the Hyper-V hypervisor driver.""")


dynamic_memory_ratio_opt = cfg.FloatOpt('dynamic_memory_ratio',
                default=1.0,
                help="""
Enables dynamic memory allocation (ballooning) when
set to a value greater than 1. The value expresses
the ratio between the total RAM assigned to an
instance and its startup RAM amount. For example a
ratio of 2.0 for an instance with 1024MB of RAM
implies 512MB of RAM allocated at startup
""")

enable_instance_metrics_collection_opt = cfg.BoolOpt(
                'enable_instance_metrics_collection',
                default=False,
                help="""
Enables metrics collections for an instance by using
Hyper-V's metric APIs. Collected data can by retrieved
by other apps and services, e.g.: Ceilometer.
Requires Hyper-V / Windows Server 2012 and above
""")

instances_path_share_opt = cfg.StrOpt('instances_path_share',
                default="",
                help="""
The name of a Windows share name mapped to the
"instances_path" dir and used by the resize feature
to copy files to the target host. If left blank, an
administrative share will be used, looking for the same
"instances_path" used locally
""")

limit_cpu_features_opt = cfg.BoolOpt('limit_cpu_features',
                default=False,
                help="""
Required for live migration among
hosts with different CPU features
""")

mounted_disk_query_retry_count_opt = cfg.IntOpt(
                'mounted_disk_query_retry_count',
                default=10,
                help="""
The number of times to retry checking for a disk mounted via iSCSI.
""")

mounted_disk_query_retry_interval_opt = cfg.IntOpt(
                'mounted_disk_query_retry_interval',
                default=5,
                help="""
Interval between checks for a mounted iSCSI disk, in seconds.
""")

power_state_check_timeframe_opt = cfg.IntOpt('power_state_check_timeframe',
                default=60,
                help="""
The timeframe to be checked for instance power state changes.
""")

power_state_event_polling_interval_opt = cfg.IntOpt(
                'power_state_event_polling_interval',
                default=2,
                help="""
Instance power state change event polling frequency.
""")

qemu_img_cmd_opt = cfg.StrOpt('qemu_img_cmd',
                default="qemu-img.exe",
                help="""
Path of qemu-img command which is used to convert
between different image types
""")

vswitch_name_opt = cfg.StrOpt('vswitch_name',
                help="""
External virtual switch Name, if not provided,
the first external virtual switch is used
""")

wait_soft_reboot_seconds_opt = cfg.IntOpt('wait_soft_reboot_seconds',
                default=60,
                help="""
Number of seconds to wait for instance to shut down after
soft reboot request is made. We fall back to hard reboot
if instance does not shutdown within this window.
""")

config_drive_cdrom_opt = cfg.BoolOpt('config_drive_cdrom',
                default=False,
                help="""
Attaches the Config Drive image as a cdrom drive
instead of a disk drive
""")

config_drive_inject_password_opt = cfg.BoolOpt('config_drive_inject_password',
                default=False,
                help="""
Sets the admin password in the config drive image
""")

volume_attach_retry_count_opt = cfg.IntOpt('volume_attach_retry_count',
                default=10,
                help="""
The number of times to retry to attach a volume
""")

volume_attach_retry_interval_opt = cfg.IntOpt('volume_attach_retry_interval',
                default=5,
                help="""
Interval between volume attachment attempts, in seconds
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
