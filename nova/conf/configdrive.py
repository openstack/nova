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

config_drive_opts = [
    cfg.StrOpt('config_drive_format',
        default='iso9660',
        choices=('iso9660', 'vfat'),
        help="""
Configuration drive format

Configuration drive format that will contain metadata attached to the
instance when it boots.

Possible values:

* iso9660: A file system image standard that is widely supported across
  operating systems. NOTE: Mind the libvirt bug
  (https://bugs.launchpad.net/nova/+bug/1246201) - If your hypervisor
  driver is libvirt, and you want live migrate to work without shared storage,
  then use VFAT.
* vfat: For legacy reasons, you can configure the configuration drive to
  use VFAT format instead of ISO 9660.

Related options:

* This option is meaningful when one of the following alternatives occur:
  1. force_config_drive option set to 'true'
  2. the REST API call to create the instance contains an enable flag for
     config drive option
  3. the image used to create the instance requires a config drive,
     this is defined by img_config_drive property for that image.
* A compute node running Hyper-V hypervisor can be configured to attach
  configuration drive as a CD drive. To attach the configuration drive as a CD
  drive, set config_drive_cdrom option at hyperv section, to true.
"""),
    cfg.BoolOpt('force_config_drive',
        default=False,
        help="""
Force injection to take place on a config drive

When this option is set to true configuration drive functionality will be
forced enabled by default, otherwise user can still enable configuration
drives via the REST API or image metadata properties.

Possible values:

* True: Force to use of configuration drive regardless the user's input in the
        REST API call.
* False: Do not force use of configuration drive. Config drives can still be
         enabled via the REST API or image metadata properties.

Related options:

* Use the 'mkisofs_cmd' flag to set the path where you install the
  genisoimage program. If genisoimage is in same path as the
  nova-compute service, you do not need to set this flag.
* To use configuration drive with Hyper-V, you must set the
  'mkisofs_cmd' value to the full path to an mkisofs.exe installation.
  Additionally, you must set the qemu_img_cmd value in the hyperv
  configuration section to the full path to an qemu-img command
  installation.
"""),
    cfg.StrOpt('mkisofs_cmd',
        default='genisoimage',
        help="""
Name or path of the tool used for ISO image creation

Use the mkisofs_cmd flag to set the path where you install the genisoimage
program. If genisoimage is on the system path, you do not need to change
the default value.

To use configuration drive with Hyper-V, you must set the mkisofs_cmd value
to the full path to an mkisofs.exe installation. Additionally, you must set
the qemu_img_cmd value in the hyperv configuration section to the full path
to an qemu-img command installation.

Possible values:

* Name of the ISO image creator program, in case it is in the same directory
  as the nova-compute service
* Path to ISO image creator program

Related options:

* This option is meaningful when config drives are enabled.
* To use configuration drive with Hyper-V, you must set the qemu_img_cmd
  value in the hyperv configuration section to the full path to an qemu-img
  command installation.
"""),
]


def register_opts(conf):
    conf.register_opts(config_drive_opts)


def list_opts():
    return {"DEFAULT": config_drive_opts}
