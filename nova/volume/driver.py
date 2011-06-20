# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
Drivers for volumes.

"""

import time
import os

from nova import exception
from nova import flags
from nova import log as logging
from nova import utils


LOG = logging.getLogger("nova.volume.driver")
FLAGS = flags.FLAGS
flags.DEFINE_string('volume_group', 'nova-volumes',
                    'Name for the VG that will contain exported volumes')
flags.DEFINE_string('aoe_eth_dev', 'eth0',
                    'Which device to export the volumes on')
flags.DEFINE_string('num_shell_tries', 3,
                    'number of times to attempt to run flakey shell commands')
flags.DEFINE_string('num_iscsi_scan_tries', 3,
                    'number of times to rescan iSCSI target to find volume')
flags.DEFINE_integer('num_shelves',
                    100,
                    'Number of vblade shelves')
flags.DEFINE_integer('blades_per_shelf',
                    16,
                    'Number of vblade blades per shelf')
flags.DEFINE_integer('iscsi_num_targets',
                    100,
                    'Number of iscsi target ids per host')
flags.DEFINE_string('iscsi_target_prefix', 'iqn.2010-10.org.openstack:',
                    'prefix for iscsi volumes')
flags.DEFINE_string('iscsi_ip_prefix', '$my_ip',
                    'discover volumes on the ip that starts with this prefix')
flags.DEFINE_string('rbd_pool', 'rbd',
                    'the rbd pool in which volumes are stored')


class VolumeDriver(object):
    """Executes commands relating to Volumes."""
    def __init__(self, execute=utils.execute,
                 sync_exec=utils.execute, *args, **kwargs):
        # NOTE(vish): db is set by Manager
        self.db = None
        self._execute = execute
        self._sync_exec = sync_exec

    def _try_execute(self, *command):
        # NOTE(vish): Volume commands can partially fail due to timing, but
        #             running them a second time on failure will usually
        #             recover nicely.
        tries = 0
        while True:
            try:
                self._execute(*command)
                return True
            except exception.ProcessExecutionError:
                tries = tries + 1
                if tries >= FLAGS.num_shell_tries:
                    raise
                LOG.exception(_("Recovering from a failed execute.  "
                                "Try number %s"), tries)
                time.sleep(tries ** 2)

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met"""
        out, err = self._execute('sudo', 'vgs', '--noheadings', '-o', 'name')
        volume_groups = out.split()
        if not FLAGS.volume_group in volume_groups:
            raise exception.Error(_("volume group %s doesn't exist")
                                  % FLAGS.volume_group)

    def _create_volume(self, volume_name, sizestr):
        self._try_execute('sudo', 'lvcreate', '-L', sizestr, '-n',
                          volume_name, FLAGS.volume_group)

    def _copy_volume(self, srcstr, deststr, size_in_g):
        self._execute('sudo', 'dd', 'if=%s' % srcstr, 'of=%s' % deststr,
                      'count=%d' % (size_in_g * 1024), 'bs=1M')

    def _volume_not_present(self, volume_name):
        path_name = '%s/%s' % (FLAGS.volume_group, volume_name)
        try:
            self._try_execute('sudo', 'lvdisplay', path_name)
        except Exception as e:
            # If the volume isn't present
            return True
        return False

    def _delete_volume(self, volume, size_in_g):
        """Deletes a logical volume."""
        # zero out old volumes to prevent data leaking between users
        # TODO(ja): reclaiming space should be done lazy and low priority
        self._copy_volume('/dev/zero', self.local_path(volume), size_in_g)
        self._try_execute('sudo', 'lvremove', '-f', "%s/%s" %
                          (FLAGS.volume_group,
                           self._escape_snapshot(volume['name'])))

    def _sizestr(self, size_in_g):
        if int(size_in_g) == 0:
            return '100M'
        return '%sG' % size_in_g

    # Linux LVM reserves name that starts with snapshot, so that
    # such volume name can't be created. Mangle it.
    def _escape_snapshot(self, snapshot_name):
        if not snapshot_name.startswith('snapshot'):
            return snapshot_name
        return '_' + snapshot_name

    def create_volume(self, volume):
        """Creates a logical volume. Can optionally return a Dictionary of
        changes to the volume object to be persisted."""
        self._create_volume(volume['name'], self._sizestr(volume['size']))

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        self._create_volume(volume['name'], self._sizestr(volume['size']))
        self._copy_volume(self.local_path(snapshot), self.local_path(volume),
                          snapshot['volume_size'])

    def delete_volume(self, volume):
        """Deletes a logical volume."""
        if self._volume_not_present(volume['name']):
            # If the volume isn't present, then don't attempt to delete
            return True

        # TODO(yamahata): lvm can't delete origin volume only without
        # deleting derived snapshots. Can we do something fancy?
        out, err = self._execute('sudo', 'lvdisplay', '--noheading',
                                 '-C', '-o', 'Attr',
                                 '%s/%s' % (FLAGS.volume_group,
                                            volume['name']))
        # fake_execute returns None resulting unit test error
        if out:
            out = out.strip()
            if (out[0] == 'o') or (out[0] == 'O'):
                raise exception.VolumeIsBusy(volume_name=volume['name'])

        self._delete_volume(volume, volume['size'])

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        orig_lv_name = "%s/%s" % (FLAGS.volume_group, snapshot['volume_name'])
        self._try_execute('sudo', 'lvcreate', '-L',
                          self._sizestr(snapshot['volume_size']),
                          '--name', self._escape_snapshot(snapshot['name']),
                          '--snapshot', orig_lv_name)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        if self._volume_not_present(self._escape_snapshot(snapshot['name'])):
            # If the snapshot isn't present, then don't attempt to delete
            return True

        # TODO(yamahata): zeroing out the whole snapshot triggers COW.
        # it's quite slow.
        self._delete_volume(snapshot, snapshot['volume_size'])

    def local_path(self, volume):
        # NOTE(vish): stops deprecation warning
        escaped_group = FLAGS.volume_group.replace('-', '--')
        escaped_name = self._escape_snapshot(volume['name']).replace('-', '--')
        return "/dev/mapper/%s-%s" % (escaped_group, escaped_name)

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        raise NotImplementedError()

    def create_export(self, context, volume):
        """Exports the volume. Can optionally return a Dictionary of changes
        to the volume object to be persisted."""
        raise NotImplementedError()

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        raise NotImplementedError()

    def discover_volume(self, context, volume):
        """Discover volume on a remote host."""
        raise NotImplementedError()

    def undiscover_volume(self, volume):
        """Undiscover volume on a remote host."""
        raise NotImplementedError()

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        raise NotImplementedError()


class AOEDriver(VolumeDriver):
    """Implements AOE specific volume commands."""

    def ensure_export(self, context, volume):
        # NOTE(vish): we depend on vblade-persist for recreating exports
        pass

    def _ensure_blades(self, context):
        """Ensure that blades have been created in datastore."""
        total_blades = FLAGS.num_shelves * FLAGS.blades_per_shelf
        if self.db.export_device_count(context) >= total_blades:
            return
        for shelf_id in xrange(FLAGS.num_shelves):
            for blade_id in xrange(FLAGS.blades_per_shelf):
                dev = {'shelf_id': shelf_id, 'blade_id': blade_id}
                self.db.export_device_create_safe(context, dev)

    def create_export(self, context, volume):
        """Creates an export for a logical volume."""
        self._ensure_blades(context)
        (shelf_id,
         blade_id) = self.db.volume_allocate_shelf_and_blade(context,
                                                             volume['id'])
        self._try_execute(
                'sudo', 'vblade-persist', 'setup',
                 shelf_id,
                 blade_id,
                 FLAGS.aoe_eth_dev,
                 "/dev/%s/%s" %
                 (FLAGS.volume_group,
                  volume['name']))
        # NOTE(vish): The standard _try_execute does not work here
        #             because these methods throw errors if other
        #             volumes on this host are in the process of
        #             being created.  The good news is the command
        #             still works for the other volumes, so we
        #             just wait a bit for the current volume to
        #             be ready and ignore any errors.
        time.sleep(2)
        self._execute('sudo', 'vblade-persist', 'auto', 'all',
                      check_exit_code=False)
        self._execute('sudo', 'vblade-persist', 'start', 'all',
                      check_exit_code=False)

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        (shelf_id,
         blade_id) = self.db.volume_get_shelf_and_blade(context,
                                                        volume['id'])
        self._try_execute('sudo', 'vblade-persist', 'stop',
                          shelf_id, blade_id)
        self._try_execute('sudo', 'vblade-persist', 'destroy',
                          shelf_id, blade_id)

    def discover_volume(self, context, _volume):
        """Discover volume on a remote host."""
        (shelf_id,
         blade_id) = self.db.volume_get_shelf_and_blade(context,
                                                        _volume['id'])
        self._execute('sudo', 'aoe-discover')
        out, err = self._execute('sudo', 'aoe-stat', check_exit_code=False)
        device_path = 'e%(shelf_id)d.%(blade_id)d' % locals()
        if out.find(device_path) >= 0:
            return "/dev/etherd/%s" % device_path
        else:
            return

    def undiscover_volume(self, _volume):
        """Undiscover volume on a remote host."""
        pass

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        (shelf_id,
         blade_id) = self.db.volume_get_shelf_and_blade(context,
                                                        volume_id)
        cmd = ('sudo', 'vblade-persist', 'ls', '--no-header')
        out, _err = self._execute(*cmd)
        exported = False
        for line in out.split('\n'):
            param = line.split(' ')
            if len(param) == 6 and param[0] == str(shelf_id) \
                    and param[1] == str(blade_id) and param[-1] == "run":
                exported = True
                break
        if not exported:
            # Instance will be terminated in this case.
            desc = _("Cannot confirm exported volume id:%(volume_id)s. "
                     "vblade process for e%(shelf_id)s.%(blade_id)s "
                     "isn't running.") % locals()
            raise exception.ProcessExecutionError(out, _err, cmd=cmd,
                                                  description=desc)


class FakeAOEDriver(AOEDriver):
    """Logs calls instead of executing."""

    def __init__(self, *args, **kwargs):
        super(FakeAOEDriver, self).__init__(execute=self.fake_execute,
                                            sync_exec=self.fake_execute,
                                            *args, **kwargs)

    def check_for_setup_error(self):
        """No setup necessary in fake mode."""
        pass

    @staticmethod
    def fake_execute(cmd, *_args, **_kwargs):
        """Execute that simply logs the command."""
        LOG.debug(_("FAKE AOE: %s"), cmd)
        return (None, None)


class ISCSIDriver(VolumeDriver):
    """Executes commands relating to ISCSI volumes.

    We make use of model provider properties as follows:

    :provider_location:    if present, contains the iSCSI target information
                           in the same format as an ietadm discovery
                           i.e. '<ip>:<port>,<portal> <target IQN>'

    :provider_auth:    if present, contains a space-separated triple:
                       '<auth method> <auth username> <auth password>'.
                       `CHAP` is the only auth_method in use at the moment.
    """

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        try:
            iscsi_target = self.db.volume_get_iscsi_target_num(context,
                                                           volume['id'])
        except exception.NotFound:
            LOG.info(_("Skipping ensure_export. No iscsi_target " +
                       "provisioned for volume: %d"), volume['id'])
            return

        iscsi_name = "%s%s" % (FLAGS.iscsi_target_prefix, volume['name'])
        volume_path = "/dev/%s/%s" % (FLAGS.volume_group, volume['name'])
        self._sync_exec('sudo', 'ietadm', '--op', 'new',
                        "--tid=%s" % iscsi_target,
                        '--params',
                        "Name=%s" % iscsi_name,
                        check_exit_code=False)
        self._sync_exec('sudo', 'ietadm', '--op', 'new',
                        "--tid=%s" % iscsi_target,
                        '--lun=0',
                        '--params',
                        "Path=%s,Type=fileio" % volume_path,
                        check_exit_code=False)

    def _ensure_iscsi_targets(self, context, host):
        """Ensure that target ids have been created in datastore."""
        host_iscsi_targets = self.db.iscsi_target_count_by_host(context, host)
        if host_iscsi_targets >= FLAGS.iscsi_num_targets:
            return
        # NOTE(vish): Target ids start at 1, not 0.
        for target_num in xrange(1, FLAGS.iscsi_num_targets + 1):
            target = {'host': host, 'target_num': target_num}
            self.db.iscsi_target_create_safe(context, target)

    def create_export(self, context, volume):
        """Creates an export for a logical volume."""
        self._ensure_iscsi_targets(context, volume['host'])
        iscsi_target = self.db.volume_allocate_iscsi_target(context,
                                                      volume['id'],
                                                      volume['host'])
        iscsi_name = "%s%s" % (FLAGS.iscsi_target_prefix, volume['name'])
        volume_path = "/dev/%s/%s" % (FLAGS.volume_group, volume['name'])
        self._execute('sudo', 'ietadm', '--op', 'new',
                      '--tid=%s' % iscsi_target,
                      '--params', 'Name=%s' % iscsi_name)
        self._execute('sudo', 'ietadm', '--op', 'new',
                      '--tid=%s' % iscsi_target,
                      '--lun=0', '--params',
                      'Path=%s,Type=fileio' % volume_path)

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        try:
            iscsi_target = self.db.volume_get_iscsi_target_num(context,
                                                           volume['id'])
        except exception.NotFound:
            LOG.info(_("Skipping remove_export. No iscsi_target " +
                       "provisioned for volume: %d"), volume['id'])
            return

        try:
            # ietadm show will exit with an error
            # this export has already been removed
            self._execute('sudo', 'ietadm', '--op', 'show',
                          '--tid=%s' % iscsi_target)
        except Exception as e:
            LOG.info(_("Skipping remove_export. No iscsi_target " +
                       "is presently exported for volume: %d"), volume['id'])
            return

        self._execute('sudo', 'ietadm', '--op', 'delete',
                      '--tid=%s' % iscsi_target,
                      '--lun=0')
        self._execute('sudo', 'ietadm', '--op', 'delete',
                      '--tid=%s' % iscsi_target)

    def _do_iscsi_discovery(self, volume):
        #TODO(justinsb): Deprecate discovery and use stored info
        #NOTE(justinsb): Discovery won't work with CHAP-secured targets (?)
        LOG.warn(_("ISCSI provider_location not stored, using discovery"))

        volume_name = volume['name']

        (out, _err) = self._execute('sudo', 'iscsiadm', '-m', 'discovery',
                                    '-t', 'sendtargets', '-p', volume['host'])
        for target in out.splitlines():
            if FLAGS.iscsi_ip_prefix in target and volume_name in target:
                return target
        return None

    def _get_iscsi_properties(self, volume):
        """Gets iscsi configuration

        We ideally get saved information in the volume entity, but fall back
        to discovery if need be. Discovery may be completely removed in future
        The properties are:

        :target_discovered:    boolean indicating whether discovery was used

        :target_iqn:    the IQN of the iSCSI target

        :target_portal:    the portal of the iSCSI target

        :auth_method:, :auth_username:, :auth_password:

            the authentication details. Right now, either auth_method is not
            present meaning no authentication, or auth_method == `CHAP`
            meaning use CHAP with the specified credentials.
        """

        properties = {}

        location = volume['provider_location']

        if location:
            # provider_location is the same format as iSCSI discovery output
            properties['target_discovered'] = False
        else:
            location = self._do_iscsi_discovery(volume)

            if not location:
                raise exception.Error(_("Could not find iSCSI export "
                                        " for volume %s") %
                                      (volume['name']))

            LOG.debug(_("ISCSI Discovery: Found %s") % (location))
            properties['target_discovered'] = True

        (iscsi_target, _sep, iscsi_name) = location.partition(" ")

        iscsi_portal = iscsi_target.split(",")[0]

        properties['target_iqn'] = iscsi_name
        properties['target_portal'] = iscsi_portal

        auth = volume['provider_auth']

        if auth:
            (auth_method, auth_username, auth_secret) = auth.split()

            properties['auth_method'] = auth_method
            properties['auth_username'] = auth_username
            properties['auth_password'] = auth_secret

        return properties

    def _run_iscsiadm(self, iscsi_properties, iscsi_command):
        (out, err) = self._execute('sudo', 'iscsiadm', '-m', 'node', '-T',
                                   iscsi_properties['target_iqn'],
                                   '-p', iscsi_properties['target_portal'],
                                   iscsi_command)
        LOG.debug("iscsiadm %s: stdout=%s stderr=%s" %
                  (iscsi_command, out, err))
        return (out, err)

    def _iscsiadm_update(self, iscsi_properties, property_key, property_value):
        iscsi_command = ('--op', 'update', '-n', property_key,
                         '-v', property_value)
        return self._run_iscsiadm(iscsi_properties, iscsi_command)

    def discover_volume(self, context, volume):
        """Discover volume on a remote host."""
        iscsi_properties = self._get_iscsi_properties(volume)

        if not iscsi_properties['target_discovered']:
            self._run_iscsiadm(iscsi_properties, ('--op', 'new'))

        if iscsi_properties.get('auth_method'):
            self._iscsiadm_update(iscsi_properties,
                                  "node.session.auth.authmethod",
                                  iscsi_properties['auth_method'])
            self._iscsiadm_update(iscsi_properties,
                                  "node.session.auth.username",
                                  iscsi_properties['auth_username'])
            self._iscsiadm_update(iscsi_properties,
                                  "node.session.auth.password",
                                  iscsi_properties['auth_password'])

        self._run_iscsiadm(iscsi_properties, "--login")

        self._iscsiadm_update(iscsi_properties, "node.startup", "automatic")

        mount_device = ("/dev/disk/by-path/ip-%s-iscsi-%s-lun-0" %
                        (iscsi_properties['target_portal'],
                         iscsi_properties['target_iqn']))

        # The /dev/disk/by-path/... node is not always present immediately
        # TODO(justinsb): This retry-with-delay is a pattern, move to utils?
        tries = 0
        while not os.path.exists(mount_device):
            if tries >= FLAGS.num_iscsi_scan_tries:
                raise exception.Error(_("iSCSI device not found at %s") %
                                      (mount_device))

            LOG.warn(_("ISCSI volume not yet found at: %(mount_device)s. "
                       "Will rescan & retry.  Try number: %(tries)s") %
                     locals())

            # The rescan isn't documented as being necessary(?), but it helps
            self._run_iscsiadm(iscsi_properties, "--rescan")

            tries = tries + 1
            if not os.path.exists(mount_device):
                time.sleep(tries ** 2)

        if tries != 0:
            LOG.debug(_("Found iSCSI node %(mount_device)s "
                        "(after %(tries)s rescans)") %
                      locals())

        return mount_device

    def undiscover_volume(self, volume):
        """Undiscover volume on a remote host."""
        iscsi_properties = self._get_iscsi_properties(volume)
        self._iscsiadm_update(iscsi_properties, "node.startup", "manual")
        self._run_iscsiadm(iscsi_properties, "--logout")
        self._run_iscsiadm(iscsi_properties, ('--op', 'delete'))

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""

        tid = self.db.volume_get_iscsi_target_num(context, volume_id)
        try:
            self._execute('sudo', 'ietadm', '--op', 'show',
                          '--tid=%(tid)d' % locals())
        except exception.ProcessExecutionError, e:
            # Instances remount read-only in this case.
            # /etc/init.d/iscsitarget restart and rebooting nova-volume
            # is better since ensure_export() works at boot time.
            logging.error(_("Cannot confirm exported volume "
                            "id:%(volume_id)s.") % locals())
            raise


class FakeISCSIDriver(ISCSIDriver):
    """Logs calls instead of executing."""
    def __init__(self, *args, **kwargs):
        super(FakeISCSIDriver, self).__init__(execute=self.fake_execute,
                                              sync_exec=self.fake_execute,
                                              *args, **kwargs)

    def check_for_setup_error(self):
        """No setup necessary in fake mode."""
        pass

    def discover_volume(self, context, volume):
        """Discover volume on a remote host."""
        return "/dev/disk/by-path/volume-id-%d" % volume['id']

    def undiscover_volume(self, volume):
        """Undiscover volume on a remote host."""
        pass

    @staticmethod
    def fake_execute(cmd, *_args, **_kwargs):
        """Execute that simply logs the command."""
        LOG.debug(_("FAKE ISCSI: %s"), cmd)
        return (None, None)


class RBDDriver(VolumeDriver):
    """Implements RADOS block device (RBD) volume commands"""

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met"""
        (stdout, stderr) = self._execute('rados', 'lspools')
        pools = stdout.split("\n")
        if not FLAGS.rbd_pool in pools:
            raise exception.Error(_("rbd has no pool %s") %
                                  FLAGS.rbd_pool)

    def create_volume(self, volume):
        """Creates a logical volume."""
        if int(volume['size']) == 0:
            size = 100
        else:
            size = int(volume['size']) * 1024
        self._try_execute('rbd', '--pool', FLAGS.rbd_pool,
                          '--size', size, 'create', volume['name'])

    def delete_volume(self, volume):
        """Deletes a logical volume."""
        self._try_execute('rbd', '--pool', FLAGS.rbd_pool,
                          'rm', volume['name'])

    def create_snapshot(self, snapshot):
        """Creates an rbd snapshot"""
        self._try_execute('rbd', '--pool', FLAGS.rbd_pool,
                          'snap', 'create', '--snap', snapshot['name'],
                          snapshot['volume_name'])

    def delete_snapshot(self, snapshot):
        """Deletes an rbd snapshot"""
        self._try_execute('rbd', '--pool', FLAGS.rbd_pool,
                          'snap', 'rm', '--snap', snapshot['name'],
                          snapshot['volume_name'])

    def local_path(self, volume):
        """Returns the path of the rbd volume."""
        # This is the same as the remote path
        # since qemu accesses it directly.
        return "rbd:%s/%s" % (FLAGS.rbd_pool, volume['name'])

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        pass

    def create_export(self, context, volume):
        """Exports the volume"""
        pass

    def remove_export(self, context, volume):
        """Removes an export for a logical volume"""
        pass

    def discover_volume(self, context, volume):
        """Discover volume on a remote host"""
        return "rbd:%s/%s" % (FLAGS.rbd_pool, volume['name'])

    def undiscover_volume(self, volume):
        """Undiscover volume on a remote host"""
        pass


class SheepdogDriver(VolumeDriver):
    """Executes commands relating to Sheepdog Volumes"""

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met"""
        try:
            (out, err) = self._execute('collie', 'cluster', 'info')
            if not out.startswith('running'):
                raise exception.Error(_("Sheepdog is not working: %s") % out)
        except exception.ProcessExecutionError:
            raise exception.Error(_("Sheepdog is not working"))

    def create_volume(self, volume):
        """Creates a sheepdog volume"""
        self._try_execute('qemu-img', 'create',
                          "sheepdog:%s" % volume['name'],
                          self._sizestr(volume['size']))

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a sheepdog volume from a snapshot."""
        self._try_execute('qemu-img', 'create', '-b',
                          "sheepdog:%s:%s" % (snapshot['volume_name'],
                                              snapshot['name']),
                          "sheepdog:%s" % volume['name'])

    def delete_volume(self, volume):
        """Deletes a logical volume"""
        self._try_execute('collie', 'vdi', 'delete', volume['name'])

    def create_snapshot(self, snapshot):
        """Creates a sheepdog snapshot"""
        self._try_execute('qemu-img', 'snapshot', '-c', snapshot['name'],
                          "sheepdog:%s" % snapshot['volume_name'])

    def delete_snapshot(self, snapshot):
        """Deletes a sheepdog snapshot"""
        self._try_execute('collie', 'vdi', 'delete', snapshot['volume_name'],
                          '-s', snapshot['name'])

    def local_path(self, volume):
        return "sheepdog:%s" % volume['name']

    def ensure_export(self, context, volume):
        """Safely and synchronously recreates an export for a logical volume"""
        pass

    def create_export(self, context, volume):
        """Exports the volume"""
        pass

    def remove_export(self, context, volume):
        """Removes an export for a logical volume"""
        pass

    def discover_volume(self, context, volume):
        """Discover volume on a remote host"""
        return "sheepdog:%s" % volume['name']

    def undiscover_volume(self, volume):
        """Undiscover volume on a remote host"""
        pass


class LoggingVolumeDriver(VolumeDriver):
    """Logs and records calls, for unit tests."""

    def check_for_setup_error(self):
        pass

    def create_volume(self, volume):
        self.log_action('create_volume', volume)

    def delete_volume(self, volume):
        self.log_action('delete_volume', volume)

    def local_path(self, volume):
        print "local_path not implemented"
        raise NotImplementedError()

    def ensure_export(self, context, volume):
        self.log_action('ensure_export', volume)

    def create_export(self, context, volume):
        self.log_action('create_export', volume)

    def remove_export(self, context, volume):
        self.log_action('remove_export', volume)

    def discover_volume(self, context, volume):
        self.log_action('discover_volume', volume)

    def undiscover_volume(self, volume):
        self.log_action('undiscover_volume', volume)

    def check_for_export(self, context, volume_id):
        self.log_action('check_for_export', volume_id)

    _LOGS = []

    @staticmethod
    def clear_logs():
        LoggingVolumeDriver._LOGS = []

    @staticmethod
    def log_action(action, parameters):
        """Logs the command."""
        LOG.debug(_("LoggingVolumeDriver: %s") % (action))
        log_dictionary = {}
        if parameters:
            log_dictionary = dict(parameters)
        log_dictionary['action'] = action
        LOG.debug(_("LoggingVolumeDriver: %s") % (log_dictionary))
        LoggingVolumeDriver._LOGS.append(log_dictionary)

    @staticmethod
    def all_logs():
        return LoggingVolumeDriver._LOGS

    @staticmethod
    def logs_like(action, **kwargs):
        matches = []
        for entry in LoggingVolumeDriver._LOGS:
            if entry['action'] != action:
                continue
            match = True
            for k, v in kwargs.iteritems():
                if entry.get(k) != v:
                    match = False
                    break
            if match:
                matches.append(entry)
        return matches
