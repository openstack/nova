# Copyright 2016 Red Hat, Inc
# Copyright 2017 Rackspace Australia
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

"""
libvirt specific routines.
"""

import binascii
import os
import stat

from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import units
from oslo_utils import uuidutils

from nova.i18n import _
import nova.privsep


LOG = logging.getLogger(__name__)


@nova.privsep.sys_admin_pctxt.entrypoint
def dmcrypt_create_volume(target, device, cipher, key_size, key):
    """Sets up a dmcrypt mapping

    :param target: device mapper logical device name
    :param device: underlying block device
    :param cipher: encryption cipher string digestible by cryptsetup
    :param key_size: encryption key size
    :param key: encoded encryption key bytestring
    """
    cmd = ('cryptsetup',
           'create',
           target,
           device,
           '--cipher=' + cipher,
           '--key-size=' + str(key_size),
           '--key-file=-')
    key = binascii.hexlify(key).decode('utf-8')
    processutils.execute(*cmd, process_input=key)


@nova.privsep.sys_admin_pctxt.entrypoint
def dmcrypt_delete_volume(target):
    """Deletes a dmcrypt mapping

    :param target: name of the mapped logical device
    """
    processutils.execute('cryptsetup', 'remove', target)


@nova.privsep.sys_admin_pctxt.entrypoint
def ploop_init(size, disk_format, fs_type, disk_path):
    """Initialize ploop disk, make it readable for non-root user

    :param disk_format: data allocation format (raw or expanded)
    :param fs_type: filesystem (ext4, ext3, none)
    :param disk_path: ploop image file
    """
    processutils.execute('ploop', 'init', '-s', size, '-f', disk_format, '-t',
                         fs_type, disk_path, check_exit_code=True)

    # Add read access for all users, because "ploop init" creates
    # disk with rw rights only for root. OpenStack user should have access
    # to the disk to request info via "qemu-img info"
    # TODO(mikal): this is a faithful rendition of the pre-privsep code from
    # the libvirt driver, but it seems undesirable to me. It would be good to
    # create the loop file with the right owner or group such that we don't
    # need to have it world readable. I don't have access to a system to test
    # this on however.
    st = os.stat(disk_path)
    os.chmod(disk_path, st.st_mode | stat.S_IROTH)


@nova.privsep.sys_admin_pctxt.entrypoint
def ploop_resize(disk_path, size):
    """Resize ploop disk

    :param disk_path: ploop image file
    :param size: new size (in bytes)
    """
    processutils.execute('prl_disk_tool', 'resize',
                         '--size', '%dM' % (size // units.Mi),
                         '--resize_partition',
                         '--hdd', disk_path,
                         check_exit_code=True)


@nova.privsep.sys_admin_pctxt.entrypoint
def ploop_restore_descriptor(image_dir, base_delta, fmt):
    """Restore ploop disk descriptor XML

    :param image_dir: path to where descriptor XML is created
    :param base_delta: ploop image file containing the data
    :param fmt: ploop data allocation format (raw or expanded)
    """
    processutils.execute('ploop', 'restore-descriptor', '-f', fmt,
                         image_dir, base_delta,
                         check_exit_code=True)


@nova.privsep.sys_admin_pctxt.entrypoint
def enable_hairpin(interface):
    """Enable hairpin mode for a libvirt guest."""
    with open('/sys/class/net/%s/brport/hairpin_mode' % interface, 'w') as f:
        f.write('1')


@nova.privsep.sys_admin_pctxt.entrypoint
def plug_infiniband_vif(vnic_mac, device_id, fabric, net_model, pci_slot):
    processutils.execute('ebrctl', 'add-port', vnic_mac, device_id,
                         fabric, net_model, pci_slot)


@nova.privsep.sys_admin_pctxt.entrypoint
def unplug_infiniband_vif(fabric, vnic_mac):
    processutils.execute('ebrctl', 'del-port', fabric, vnic_mac)


@nova.privsep.sys_admin_pctxt.entrypoint
def plug_midonet_vif(port_id, dev):
    processutils.execute('mm-ctl', '--bind-port', port_id, dev)


@nova.privsep.sys_admin_pctxt.entrypoint
def unplug_midonet_vif(port_id):
    processutils.execute('mm-ctl', '--unbind-port', port_id)


@nova.privsep.sys_admin_pctxt.entrypoint
def plug_plumgrid_vif(dev, iface_id, vif_address, net_id, tenant_id):
    processutils.execute('ifc_ctl', 'gateway', 'add_port', dev)
    processutils.execute('ifc_ctl', 'gateway', 'ifup', dev,
                         'access_vm', iface_id, vif_address,
                         'pgtag2=%s' % net_id, 'pgtag1=%s' % tenant_id)


@nova.privsep.sys_admin_pctxt.entrypoint
def unplug_plumgrid_vif(dev):
    processutils.execute('ifc_ctl', 'gateway', 'ifdown', dev)
    processutils.execute('ifc_ctl', 'gateway', 'del_port', dev)


@nova.privsep.sys_admin_pctxt.entrypoint
def readpty(path):
    # TODO(mikal): I'm not a huge fan that we don't enforce a valid pty path
    # here, but I haven't come up with a great way of doing that.

    # NOTE(mikal): I am deliberately not catching the ImportError
    # exception here... Some platforms (I'm looking at you Windows)
    # don't have a fcntl and we may as well let them know that
    # with an ImportError, not that they should be calling this at all.
    import fcntl

    try:
        with open(path, 'r') as f:
            current_flags = fcntl.fcntl(f.fileno(), fcntl.F_GETFL)
            fcntl.fcntl(f.fileno(), fcntl.F_SETFL,
                        current_flags | os.O_NONBLOCK)

            return f.read()

    except Exception as e:
        # NOTE(mikal): dear internet, I see you looking at me with your
        # judging eyes. There's a story behind why we do this. You see, the
        # previous implementation did this:
        #
        # out, err = utils.execute('dd',
        #                          'if=%s' % pty,
        #                          'iflag=nonblock',
        #                          run_as_root=True,
        #                          check_exit_code=False)
        # return out
        #
        # So, it never checked stderr or the return code of the process it
        # ran to read the pty. Doing something better than that has turned
        # out to be unexpectedly hard because there are a surprisingly large
        # variety of errors which appear to be thrown when doing this read.
        #
        # Therefore for now we log the errors, but keep on rolling. Volunteers
        # to help clean this up are welcome and will receive free beverages.
        LOG.info(_('Ignored error while reading from instance console '
                   'pty: %s'), e)
        return ''


@nova.privsep.sys_admin_pctxt.entrypoint
def xend_probe():
    processutils.execute('xend', 'status', check_exit_code=True)


@nova.privsep.sys_admin_pctxt.entrypoint
def create_mdev(physical_device, mdev_type, uuid=None):
    """Instantiate a mediated device."""
    if uuid is None:
        uuid = uuidutils.generate_uuid()
    fpath = '/sys/class/mdev_bus/{0}/mdev_supported_types/{1}/create'
    fpath = fpath.format(physical_device, mdev_type)
    with open(fpath, 'w') as f:
        f.write(uuid)
    return uuid


@nova.privsep.sys_admin_pctxt.entrypoint
def systemd_run_qb_mount(qb_vol, mnt_base, cfg_file=None):
    """Mount QB volume in separate CGROUP"""
    # Note(kaisers): Details on why we run without --user at bug #1756823
    sysdr_cmd = ['systemd-run', '--scope', 'mount.quobyte', '--disable-xattrs',
                 qb_vol, mnt_base]
    if cfg_file:
        sysdr_cmd.extend(['-c', cfg_file])
    return processutils.execute(*sysdr_cmd)


# NOTE(kaisers): this method is deliberately not wrapped in a privsep entry.
def unprivileged_qb_mount(qb_vol, mnt_base, cfg_file=None):
    """Mount QB volume"""
    mnt_cmd = ['mount.quobyte', '--disable-xattrs', qb_vol, mnt_base]
    if cfg_file:
        mnt_cmd.extend(['-c', cfg_file])
    return processutils.execute(*mnt_cmd)


@nova.privsep.sys_admin_pctxt.entrypoint
def umount(mnt_base):
    """Unmount volume"""
    unprivileged_umount(mnt_base)


# NOTE(kaisers): this method is deliberately not wrapped in a privsep entry.
def unprivileged_umount(mnt_base):
    """Unmount volume"""
    umnt_cmd = ['umount', mnt_base]
    return processutils.execute(*umnt_cmd)


@nova.privsep.sys_admin_pctxt.entrypoint
def get_pmem_namespaces():
    ndctl_cmd = ['ndctl', 'list', '-X']
    nss_info = processutils.execute(*ndctl_cmd)[0]
    return nss_info


@nova.privsep.sys_admin_pctxt.entrypoint
def cleanup_vpmem(devpath):
    daxio_cmd = ['daxio', '-z', '-o', '%s' % devpath]
    processutils.execute(*daxio_cmd)
