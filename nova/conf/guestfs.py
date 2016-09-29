# Copyright 2015 OpenStack Foundation
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

guestfs_group = cfg.OptGroup('guestfs',
                             title='Guestfs Options',
                             help="""
libguestfs is a set of tools for accessing and modifying virtual
machine (VM) disk images. You can use this for viewing and editing
files inside guests, scripting changes to VMs, monitoring disk
used/free statistics, creating guests, P2V, V2V, performing backups,
cloning VMs, building VMs, formatting disks and resizing disks.
""")

enable_guestfs_debug_opts = [
    cfg.BoolOpt('debug',
                default=False,
                help="""
Enable/disables guestfs logging.

This configures guestfs to debug messages and push them to Openstack
logging system. When set to True, it traces libguestfs API calls and
enable verbose debug messages. In order to use the above feature,
"libguestfs" package must be installed.

Related options:
Since libguestfs access and modifies VM's managed by libvirt, below options
should be set to give access to those VM's.
    * libvirt.inject_key
    * libvirt.inject_partition
    * libvirt.inject_password
""")
]


def register_opts(conf):
    conf.register_group(guestfs_group)
    conf.register_opts(enable_guestfs_debug_opts,
                       group=guestfs_group)


def list_opts():
    return {guestfs_group: enable_guestfs_debug_opts}
