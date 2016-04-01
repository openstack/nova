# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import itertools

import nova.conf
import nova.virt.configdrive
import nova.virt.disk.vfs.guestfs
import nova.virt.libvirt.driver
import nova.virt.libvirt.imagebackend
import nova.virt.libvirt.imagecache
import nova.virt.libvirt.storage.lvm
import nova.virt.libvirt.utils
import nova.virt.libvirt.vif
import nova.virt.libvirt.volume.aoe
import nova.virt.libvirt.volume.glusterfs
import nova.virt.libvirt.volume.iscsi
import nova.virt.libvirt.volume.iser
import nova.virt.libvirt.volume.net
import nova.virt.libvirt.volume.nfs
import nova.virt.libvirt.volume.quobyte
import nova.virt.libvirt.volume.remotefs
import nova.virt.libvirt.volume.scality
import nova.virt.libvirt.volume.smbfs
import nova.virt.libvirt.volume.volume
import nova.virt.vmwareapi.driver
import nova.virt.vmwareapi.images
import nova.virt.vmwareapi.vif
import nova.virt.vmwareapi.vim_util
import nova.virt.vmwareapi.vm_util
import nova.virt.vmwareapi.vmops
import nova.virt.xenapi.agent
import nova.virt.xenapi.client.session
import nova.virt.xenapi.driver
import nova.virt.xenapi.image.bittorrent
import nova.virt.xenapi.pool
import nova.virt.xenapi.vif
import nova.virt.xenapi.vm_utils
import nova.virt.xenapi.vmops
import nova.virt.xenapi.volume_utils


def list_opts():
    return [
        ('DEFAULT',
         itertools.chain(
             nova.virt.configdrive.configdrive_opts,
         )),
        ('guestfs', nova.virt.disk.vfs.guestfs.guestfs_opts),
        ('libvirt',
         itertools.chain(
             nova.virt.libvirt.driver.libvirt_opts,
             nova.virt.libvirt.imagebackend.__imagebackend_opts,
             nova.virt.libvirt.imagecache.imagecache_opts,
             nova.virt.libvirt.storage.lvm.lvm_opts,
             nova.virt.libvirt.utils.libvirt_opts,
             nova.virt.libvirt.vif.libvirt_vif_opts,
             nova.virt.libvirt.volume.volume.volume_opts,
             nova.virt.libvirt.volume.aoe.volume_opts,
             nova.virt.libvirt.volume.glusterfs.volume_opts,
             nova.virt.libvirt.volume.iscsi.volume_opts,
             nova.virt.libvirt.volume.iser.volume_opts,
             nova.virt.libvirt.volume.net.volume_opts,
             nova.virt.libvirt.volume.nfs.volume_opts,
             nova.virt.libvirt.volume.quobyte.volume_opts,
             nova.virt.libvirt.volume.remotefs.libvirt_opts,
             nova.virt.libvirt.volume.scality.volume_opts,
             nova.virt.libvirt.volume.smbfs.volume_opts,
         )),
        ('vmware',
         itertools.chain(
             [nova.virt.vmwareapi.vim_util.vmware_opts],
             nova.virt.vmwareapi.driver.spbm_opts,
             nova.virt.vmwareapi.driver.vmwareapi_opts,
             nova.virt.vmwareapi.vif.vmwareapi_vif_opts,
             nova.virt.vmwareapi.vm_util.vmware_utils_opts,
             nova.virt.vmwareapi.vmops.vmops_opts,
         )),
        ('xenserver',
         itertools.chain(
             [nova.virt.xenapi.vif.xenapi_ovs_integration_bridge_opt],
             nova.virt.xenapi.driver.xenapi_opts,
             nova.virt.xenapi.image.bittorrent.xenapi_torrent_opts,
             nova.virt.xenapi.pool.xenapi_pool_opts,
             nova.virt.xenapi.vm_utils.xenapi_vm_utils_opts,
             nova.virt.xenapi.vmops.xenapi_vmops_opts,
             nova.virt.xenapi.volume_utils.xenapi_volume_utils_opts,
         )),
    ]
