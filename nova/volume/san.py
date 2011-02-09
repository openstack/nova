# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Justin Santa Barbara
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
"""
Drivers for san-stored volumes.
The unique thing about a SAN is that we don't expect that we can run the volume
 controller on the SAN hardware.  We expect to access it over SSH or some API.
"""

import os
import paramiko

from nova import exception
from nova import flags
from nova import log as logging
from nova.utils import ssh_execute
from nova.volume.driver import ISCSIDriver

LOG = logging.getLogger("nova.volume.driver")
FLAGS = flags.FLAGS
flags.DEFINE_boolean('san_thin_provision', 'true',
                     'Use thin provisioning for SAN volumes?')
flags.DEFINE_string('san_ip', '',
                    'IP address of SAN controller')
flags.DEFINE_string('san_login', 'admin',
                    'Username for SAN controller')
flags.DEFINE_string('san_password', '',
                    'Password for SAN controller')
flags.DEFINE_string('san_privatekey', '',
                    'Filename of private key to use for SSH authentication')


class SanISCSIDriver(ISCSIDriver):
    """ Base class for SAN-style storage volumes
        (storage providers we access over SSH)"""
    #Override because SAN ip != host ip
    def _get_name_and_portal(self, volume):
        """Gets iscsi name and portal from volume name and host."""
        volume_name = volume['name']

        # TODO(justinsb): store in volume, remerge with generic iSCSI code
        host = FLAGS.san_ip

        (out, _err) = self._execute("sudo iscsiadm -m discovery -t "
                                    "sendtargets -p %s" % host)

        location = None
        find_iscsi_name = self._build_iscsi_target_name(volume)
        for target in out.splitlines():
            if find_iscsi_name in target:
                (location, _sep, iscsi_name) = target.partition(" ")
                break
        if not location:
            raise exception.Error(_("Could not find iSCSI export "
                                    " for volume %s") %
                                  volume_name)

        iscsi_portal = location.split(",")[0]
        LOG.debug("iscsi_name=%s, iscsi_portal=%s" %
                  (iscsi_name, iscsi_portal))
        return (iscsi_name, iscsi_portal)

    def _build_iscsi_target_name(self, volume):
        return "%s%s" % (FLAGS.iscsi_target_prefix, volume['name'])

    # discover_volume is still OK
    # undiscover_volume is still OK

    def _connect_to_ssh(self):
        ssh = paramiko.SSHClient()
        #TODO(justinsb): We need a better SSH key policy
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if FLAGS.san_password:
            ssh.connect(FLAGS.san_ip,
                        username=FLAGS.san_login,
                        password=FLAGS.san_password)
        elif FLAGS.san_privatekey:
            privatekeyfile = os.path.expanduser(FLAGS.san_privatekey)
            # It sucks that paramiko doesn't support DSA keys
            privatekey = paramiko.RSAKey.from_private_key_file(privatekeyfile)
            ssh.connect(FLAGS.san_ip,
                        username=FLAGS.san_login,
                        pkey=privatekey)
        else:
            raise exception.Error("Specify san_password or san_privatekey")
        return ssh

    def _run_ssh(self, command, check_exit_code=True):
        #TODO(justinsb): SSH connection caching (?)
        ssh = self._connect_to_ssh()

        #TODO(justinsb): Reintroduce the retry hack
        ret = ssh_execute(ssh, command, check_exit_code=check_exit_code)

        ssh.close()

        return ret

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        pass

    def create_export(self, context, volume):
        """Exports the volume."""
        pass

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        pass

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met"""
        if not (FLAGS.san_password or FLAGS.san_privatekey):
            raise exception.Error("Specify san_password or san_privatekey")

        if not (FLAGS.san_ip):
            raise exception.Error("san_ip must be set")


def _collect_lines(data):
    """ Split lines from data into an array, trimming them """
    matches = []
    for line in data.splitlines():
        match = line.strip()
        matches.append(match)

    return matches


def _get_prefixed_values(data, prefix):
    """Collect lines which start with prefix; with trimming"""
    matches = []
    for line in data.splitlines():
        line = line.strip()
        if line.startswith(prefix):
            match = line[len(prefix):]
            match = match.strip()
            matches.append(match)

    return matches


class SolarisISCSIDriver(SanISCSIDriver):
    """Executes commands relating to Solaris-hosted ISCSI volumes.
    Basic setup for a Solaris iSCSI server:
    pkg install storage-server SUNWiscsit
    svcadm enable stmf
    svcadm enable -r svc:/network/iscsi/target:default
    pfexec itadm create-tpg e1000g0 ${MYIP}
    pfexec itadm create-target -t e1000g0

    Then grant the user that will be logging on lots of permissions.
    I'm not sure exactly which though:
    zfs allow justinsb create,mount,destroy rpool
    usermod -P'File System Management' justinsb
    usermod -P'Primary Administrator' justinsb

    Also make sure you can login using san_login & san_password/san_privatekey
    """

    def _view_exists(self, luid):
        cmd = "pfexec /usr/sbin/stmfadm list-view -l %s" % (luid)
        (out, _err) = self._run_ssh(cmd,
                                    check_exit_code=False)
        if "no views found" in out:
            return False

        if "View Entry:" in out:
            return True

        raise exception.Error("Cannot parse list-view output: %s" % (out))

    def _get_target_groups(self):
        """Gets list of target groups from host."""
        (out, _err) = self._run_ssh("pfexec /usr/sbin/stmfadm list-tg")
        matches = _get_prefixed_values(out, 'Target group: ')
        LOG.debug("target_groups=%s" % matches)
        return matches

    def _target_group_exists(self, target_group_name):
        return target_group_name not in self._get_target_groups()

    def _get_target_group_members(self, target_group_name):
        (out, _err) = self._run_ssh("pfexec /usr/sbin/stmfadm list-tg -v %s" %
                                    (target_group_name))
        matches = _get_prefixed_values(out, 'Member: ')
        LOG.debug("members of %s=%s" % (target_group_name, matches))
        return matches

    def _is_target_group_member(self, target_group_name, iscsi_target_name):
        return iscsi_target_name in (
            self._get_target_group_members(target_group_name))

    def _get_iscsi_targets(self):
        cmd = ("pfexec /usr/sbin/itadm list-target | "
               "awk '{print $1}' | grep -v ^TARGET")
        (out, _err) = self._run_ssh(cmd)
        matches = _collect_lines(out)
        LOG.debug("_get_iscsi_targets=%s" % (matches))
        return matches

    def _iscsi_target_exists(self, iscsi_target_name):
        return iscsi_target_name in self._get_iscsi_targets()

    def _build_zfs_poolname(self, volume):
        #TODO(justinsb): rpool should be configurable
        zfs_poolname = 'rpool/%s' % (volume['name'])
        return zfs_poolname

    def create_volume(self, volume):
        """Creates a volume."""
        if int(volume['size']) == 0:
            sizestr = '100M'
        else:
            sizestr = '%sG' % volume['size']

        zfs_poolname = self._build_zfs_poolname(volume)

        thin_provision_arg = '-s' if FLAGS.san_thin_provision else ''
        # Create a zfs volume
        self._run_ssh("pfexec /usr/sbin/zfs create %s -V %s %s" %
                      (thin_provision_arg,
                       sizestr,
                       zfs_poolname))

    def _get_luid(self, volume):
        zfs_poolname = self._build_zfs_poolname(volume)

        cmd = ("pfexec /usr/sbin/sbdadm list-lu | "
               "grep -w %s | awk '{print $1}'" %
               (zfs_poolname))

        (stdout, _stderr) = self._run_ssh(cmd)

        luid = stdout.strip()
        return luid

    def _is_lu_created(self, volume):
        luid = self._get_luid(volume)
        return luid

    def delete_volume(self, volume):
        """Deletes a volume."""
        zfs_poolname = self._build_zfs_poolname(volume)
        self._run_ssh("pfexec /usr/sbin/zfs destroy %s" %
                      (zfs_poolname))

    def local_path(self, volume):
        # TODO(justinsb): Is this needed here?
        escaped_group = FLAGS.volume_group.replace('-', '--')
        escaped_name = volume['name'].replace('-', '--')
        return "/dev/mapper/%s-%s" % (escaped_group, escaped_name)

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        #TODO(justinsb): On bootup, this is called for every volume.
        # It then runs ~5 SSH commands for each volume,
        # most of which fetch the same info each time
        # This makes initial start stupid-slow
        self._do_export(volume, force_create=False)

    def create_export(self, context, volume):
        self._do_export(volume, force_create=True)

    def _do_export(self, volume, force_create):
        # Create a Logical Unit (LU) backed by the zfs volume
        zfs_poolname = self._build_zfs_poolname(volume)

        if force_create or not self._is_lu_created(volume):
            cmd = ("pfexec /usr/sbin/sbdadm create-lu /dev/zvol/rdsk/%s" %
                   (zfs_poolname))
            self._run_ssh(cmd)

        luid = self._get_luid(volume)
        iscsi_name = self._build_iscsi_target_name(volume)
        target_group_name = 'tg-%s' % volume['name']

        # Create a iSCSI target, mapped to just this volume
        if force_create or not self._target_group_exists(target_group_name):
            self._run_ssh("pfexec /usr/sbin/stmfadm create-tg %s" %
                          (target_group_name))

        # Yes, we add the initiatior before we create it!
        # Otherwise, it complains that the target is already active
        if force_create or not self._is_target_group_member(target_group_name,
                                                            iscsi_name):
            self._run_ssh("pfexec /usr/sbin/stmfadm add-tg-member -g %s %s" %
                          (target_group_name, iscsi_name))
        if force_create or not self._iscsi_target_exists(iscsi_name):
            self._run_ssh("pfexec /usr/sbin/itadm create-target -n %s" %
                          (iscsi_name))
        if force_create or not self._view_exists(luid):
            self._run_ssh("pfexec /usr/sbin/stmfadm add-view -t %s %s" %
                          (target_group_name, luid))

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""

        # This is the reverse of _do_export
        luid = self._get_luid(volume)
        iscsi_name = self._build_iscsi_target_name(volume)
        target_group_name = 'tg-%s' % volume['name']

        if self._view_exists(luid):
            self._run_ssh("pfexec /usr/sbin/stmfadm remove-view -l %s -a" %
                          (luid))

        if self._iscsi_target_exists(iscsi_name):
            self._run_ssh("pfexec /usr/sbin/stmfadm offline-target %s" %
                          (iscsi_name))
            self._run_ssh("pfexec /usr/sbin/itadm delete-target %s" %
                          (iscsi_name))

        # We don't delete the tg-member; we delete the whole tg!

        if self._target_group_exists(target_group_name):
            self._run_ssh("pfexec /usr/sbin/stmfadm delete-tg %s" %
                          (target_group_name))

        if self._is_lu_created(volume):
            self._run_ssh("pfexec /usr/sbin/sbdadm delete-lu %s" %
                          (luid))
