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

from xml.etree import ElementTree

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
flags.DEFINE_string('san_clustername', '',
                    'Cluster name to use for creating volumes')
flags.DEFINE_integer('san_ssh_port', 22,
                    'SSH port to use with SAN')


class SanISCSIDriver(ISCSIDriver):
    """ Base class for SAN-style storage volumes

    A SAN-style storage value is 'different' because the volume controller
    probably won't run on it, so we need to access is over SSH or another
    remote protocol.
    """

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
                        port=FLAGS.san_ssh_port,
                        username=FLAGS.san_login,
                        password=FLAGS.san_password)
        elif FLAGS.san_privatekey:
            privatekeyfile = os.path.expanduser(FLAGS.san_privatekey)
            # It sucks that paramiko doesn't support DSA keys
            privatekey = paramiko.RSAKey.from_private_key_file(privatekeyfile)
            ssh.connect(FLAGS.san_ip,
                        port=FLAGS.san_ssh_port,
                        username=FLAGS.san_login,
                        pkey=privatekey)
        else:
            raise exception.Error(_("Specify san_password or san_privatekey"))
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
            raise exception.Error(_("Specify san_password or san_privatekey"))

        if not (FLAGS.san_ip):
            raise exception.Error(_("san_ip must be set"))


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

        #TODO(justinsb): Is this always 1? Does it matter?
        iscsi_portal_interface = '1'
        iscsi_portal = FLAGS.san_ip + ":3260," + iscsi_portal_interface

        db_update = {}
        db_update['provider_location'] = ("%s %s" %
                                          (iscsi_portal,
                                           iscsi_name))

        return db_update

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


class HpSanISCSIDriver(SanISCSIDriver):
    """Executes commands relating to HP/Lefthand SAN ISCSI volumes.

    We use the CLIQ interface, over SSH.

    Rough overview of CLIQ commands used:

    :createVolume:    (creates the volume)

    :getVolumeInfo:    (to discover the IQN etc)

    :getClusterInfo:    (to discover the iSCSI target IP address)

    :assignVolumeChap:    (exports it with CHAP security)

    The 'trick' here is that the HP SAN enforces security by default, so
    normally a volume mount would need both to configure the SAN in the volume
    layer and do the mount on the compute layer.  Multi-layer operations are
    not catered for at the moment in the nova architecture, so instead we
    share the volume using CHAP at volume creation time.  Then the mount need
    only use those CHAP credentials, so can take place exclusively in the
    compute layer.
    """

    def _cliq_run(self, verb, cliq_args):
        """Runs a CLIQ command over SSH, without doing any result parsing"""
        cliq_arg_strings = []
        for k, v in cliq_args.items():
            cliq_arg_strings.append(" %s=%s" % (k, v))
        cmd = verb + ''.join(cliq_arg_strings)

        return self._run_ssh(cmd)

    def _cliq_run_xml(self, verb, cliq_args, check_cliq_result=True):
        """Runs a CLIQ command over SSH, parsing and checking the output"""
        cliq_args['output'] = 'XML'
        (out, _err) = self._cliq_run(verb, cliq_args)

        LOG.debug(_("CLIQ command returned %s"), out)

        result_xml = ElementTree.fromstring(out)
        if check_cliq_result:
            response_node = result_xml.find("response")
            if response_node is None:
                msg = (_("Malformed response to CLIQ command "
                         "%(verb)s %(cliq_args)s. Result=%(out)s") %
                       locals())
                raise exception.Error(msg)

            result_code = response_node.attrib.get("result")

            if result_code != "0":
                msg = (_("Error running CLIQ command %(verb)s %(cliq_args)s. "
                         " Result=%(out)s") %
                       locals())
                raise exception.Error(msg)

        return result_xml

    def _cliq_get_cluster_info(self, cluster_name):
        """Queries for info about the cluster (including IP)"""
        cliq_args = {}
        cliq_args['clusterName'] = cluster_name
        cliq_args['searchDepth'] = '1'
        cliq_args['verbose'] = '0'

        result_xml = self._cliq_run_xml("getClusterInfo", cliq_args)

        return result_xml

    def _cliq_get_cluster_vip(self, cluster_name):
        """Gets the IP on which a cluster shares iSCSI volumes"""
        cluster_xml = self._cliq_get_cluster_info(cluster_name)

        vips = []
        for vip in cluster_xml.findall("response/cluster/vip"):
            vips.append(vip.attrib.get('ipAddress'))

        if len(vips) == 1:
            return vips[0]

        _xml = ElementTree.tostring(cluster_xml)
        msg = (_("Unexpected number of virtual ips for cluster "
                 " %(cluster_name)s. Result=%(_xml)s") %
               locals())
        raise exception.Error(msg)

    def _cliq_get_volume_info(self, volume_name):
        """Gets the volume info, including IQN"""
        cliq_args = {}
        cliq_args['volumeName'] = volume_name
        result_xml = self._cliq_run_xml("getVolumeInfo", cliq_args)

        # Result looks like this:
        #<gauche version="1.0">
        #  <response description="Operation succeeded." name="CliqSuccess"
        #            processingTime="87" result="0">
        #    <volume autogrowPages="4" availability="online" blockSize="1024"
        #       bytesWritten="0" checkSum="false" clusterName="Cluster01"
        #       created="2011-02-08T19:56:53Z" deleting="false" description=""
        #       groupName="Group01" initialQuota="536870912" isPrimary="true"
        #       iscsiIqn="iqn.2003-10.com.lefthandnetworks:group01:25366:vol-b"
        #       maxSize="6865387257856" md5="9fa5c8b2cca54b2948a63d833097e1ca"
        #       minReplication="1" name="vol-b" parity="0" replication="2"
        #       reserveQuota="536870912" scratchQuota="4194304"
        #       serialNumber="9fa5c8b2cca54b2948a63d833097e1ca0000000000006316"
        #       size="1073741824" stridePages="32" thinProvision="true">
        #      <status description="OK" value="2"/>
        #      <permission access="rw"
        #            authGroup="api-34281B815713B78-(trimmed)51ADD4B7030853AA7"
        #            chapName="chapusername" chapRequired="true" id="25369"
        #            initiatorSecret="" iqn="" iscsiEnabled="true"
        #            loadBalance="true" targetSecret="supersecret"/>
        #    </volume>
        #  </response>
        #</gauche>

        # Flatten the nodes into a dictionary; use prefixes to avoid collisions
        volume_attributes = {}

        volume_node = result_xml.find("response/volume")
        for k, v in volume_node.attrib.items():
            volume_attributes["volume." + k] = v

        status_node = volume_node.find("status")
        if not status_node is None:
            for k, v in status_node.attrib.items():
                volume_attributes["status." + k] = v

        # We only consider the first permission node
        permission_node = volume_node.find("permission")
        if not permission_node is None:
            for k, v in status_node.attrib.items():
                volume_attributes["permission." + k] = v

        LOG.debug(_("Volume info: %(volume_name)s => %(volume_attributes)s") %
                  locals())
        return volume_attributes

    def create_volume(self, volume):
        """Creates a volume."""
        cliq_args = {}
        cliq_args['clusterName'] = FLAGS.san_clustername
        #TODO(justinsb): Should we default to inheriting thinProvision?
        cliq_args['thinProvision'] = '1' if FLAGS.san_thin_provision else '0'
        cliq_args['volumeName'] = volume['name']
        if int(volume['size']) == 0:
            cliq_args['size'] = '100MB'
        else:
            cliq_args['size'] = '%sGB' % volume['size']

        self._cliq_run_xml("createVolume", cliq_args)

        volume_info = self._cliq_get_volume_info(volume['name'])
        cluster_name = volume_info['volume.clusterName']
        iscsi_iqn = volume_info['volume.iscsiIqn']

        #TODO(justinsb): Is this always 1? Does it matter?
        cluster_interface = '1'

        cluster_vip = self._cliq_get_cluster_vip(cluster_name)
        iscsi_portal = cluster_vip + ":3260," + cluster_interface

        model_update = {}
        model_update['provider_location'] = ("%s %s" %
                                             (iscsi_portal,
                                              iscsi_iqn))

        return model_update

    def delete_volume(self, volume):
        """Deletes a volume."""
        cliq_args = {}
        cliq_args['volumeName'] = volume['name']
        cliq_args['prompt'] = 'false'  # Don't confirm

        self._cliq_run_xml("deleteVolume", cliq_args)

    def local_path(self, volume):
        # TODO(justinsb): Is this needed here?
        raise exception.Error(_("local_path not supported"))

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        return self._do_export(context, volume, force_create=False)

    def create_export(self, context, volume):
        return self._do_export(context, volume, force_create=True)

    def _do_export(self, context, volume, force_create):
        """Supports ensure_export and create_export"""
        volume_info = self._cliq_get_volume_info(volume['name'])

        is_shared = 'permission.authGroup' in volume_info

        model_update = {}

        should_export = False

        if force_create or not is_shared:
            should_export = True
            # Check that we have a project_id
            project_id = volume['project_id']
            if not project_id:
                project_id = context.project_id

            if project_id:
                #TODO(justinsb): Use a real per-project password here
                chap_username = 'proj_' + project_id
                # HP/Lefthand requires that the password be >= 12 characters
                chap_password = 'project_secret_' + project_id
            else:
                msg = (_("Could not determine project for volume %s, "
                         "can't export") %
                         (volume['name']))
                if force_create:
                    raise exception.Error(msg)
                else:
                    LOG.warn(msg)
                    should_export = False

        if should_export:
            cliq_args = {}
            cliq_args['volumeName'] = volume['name']
            cliq_args['chapName'] = chap_username
            cliq_args['targetSecret'] = chap_password

            self._cliq_run_xml("assignVolumeChap", cliq_args)

            model_update['provider_auth'] = ("CHAP %s %s" %
                                             (chap_username, chap_password))

        return model_update

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        cliq_args = {}
        cliq_args['volumeName'] = volume['name']

        self._cliq_run_xml("unassignVolume", cliq_args)
