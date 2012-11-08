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

import os
import re
import tempfile
import time
import urllib

from nova import exception
from nova import flags
from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova import utils
from nova.volume import iscsi


LOG = logging.getLogger(__name__)

volume_opts = [
    cfg.StrOpt('volume_group',
               default='nova-volumes',
               help='Name for the VG that will contain exported volumes'),
    cfg.IntOpt('num_shell_tries',
               default=3,
               help='number of times to attempt to run flakey shell commands'),
    cfg.IntOpt('num_iscsi_scan_tries',
               default=3,
               help='number of times to rescan iSCSI target to find volume'),
    cfg.IntOpt('iscsi_num_targets',
               default=100,
               help='Number of iscsi target ids per host'),
    cfg.StrOpt('iscsi_target_prefix',
               default='iqn.2010-10.org.openstack:',
               help='prefix for iscsi volumes'),
    cfg.StrOpt('iscsi_ip_address',
               default='$my_ip',
               help='use this ip for iscsi'),
    cfg.IntOpt('iscsi_port',
               default=3260,
               help='The port that the iSCSI daemon is listening on'),
    cfg.StrOpt('rbd_pool',
               default='rbd',
               help='the RADOS pool in which rbd volumes are stored'),
    cfg.StrOpt('rbd_user',
               default=None,
               help='the RADOS client name for accessing rbd volumes'),
    cfg.StrOpt('rbd_secret_uuid',
               default=None,
               help='the libvirt uuid of the secret for the rbd_user'
                    'volumes'),
    cfg.StrOpt('volume_tmp_dir',
               default=None,
               help='where to store temporary image files if the volume '
                    'driver does not write them directly to the volume'),
    ]

FLAGS = flags.FLAGS
FLAGS.register_opts(volume_opts)


class VolumeDriver(object):
    """Executes commands relating to Volumes."""
    def __init__(self, execute=utils.execute, *args, **kwargs):
        # NOTE(vish): db is set by Manager
        self.db = None
        self.set_execute(execute)

    def set_execute(self, execute):
        self._execute = execute

    def _try_execute(self, *command, **kwargs):
        # NOTE(vish): Volume commands can partially fail due to timing, but
        #             running them a second time on failure will usually
        #             recover nicely.
        tries = 0
        while True:
            try:
                self._execute(*command, **kwargs)
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
        out, err = self._execute('vgs', '--noheadings', '-o', 'name',
                                run_as_root=True)
        volume_groups = out.split()
        if not FLAGS.volume_group in volume_groups:
            exception_message = (_("volume group %s doesn't exist")
                                  % FLAGS.volume_group)
            raise exception.VolumeBackendAPIException(data=exception_message)

    def _create_volume(self, volume_name, sizestr):
        self._try_execute('lvcreate', '-L', sizestr, '-n',
                          volume_name, FLAGS.volume_group, run_as_root=True)

    def _copy_volume(self, srcstr, deststr, size_in_g):
        # Use O_DIRECT to avoid thrashing the system buffer cache
        direct_flags = ('iflag=direct', 'oflag=direct')

        # Check whether O_DIRECT is supported
        try:
            self._execute('dd', 'count=0', 'if=%s' % srcstr, 'of=%s' % deststr,
                          *direct_flags, run_as_root=True)
        except exception.ProcessExecutionError:
            direct_flags = ()

        # Perform the copy
        self._execute('dd', 'if=%s' % srcstr, 'of=%s' % deststr,
                      'count=%d' % (size_in_g * 1024), 'bs=1M',
                      *direct_flags, run_as_root=True)

    def _volume_not_present(self, volume_name):
        path_name = '%s/%s' % (FLAGS.volume_group, volume_name)
        try:
            self._try_execute('lvdisplay', path_name, run_as_root=True)
        except Exception as e:
            # If the volume isn't present
            return True
        return False

    def _delete_volume(self, volume, size_in_g):
        """Deletes a logical volume."""
        # zero out old volumes to prevent data leaking between users
        # TODO(ja): reclaiming space should be done lazy and low priority
        self._copy_volume('/dev/zero', self.local_path(volume), size_in_g)
        dev_path = self.local_path(volume)
        if os.path.exists(dev_path):
            self._try_execute('dmsetup', 'remove', '-f', dev_path,
                              run_as_root=True)
        self._try_execute('lvremove', '-f', "%s/%s" %
                          (FLAGS.volume_group,
                           self._escape_snapshot(volume['name'])),
                          run_as_root=True)

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
        out, err = self._execute('lvdisplay', '--noheading',
                                 '-C', '-o', 'Attr',
                                 '%s/%s' % (FLAGS.volume_group,
                                            volume['name']),
                                 run_as_root=True)
        # fake_execute returns None resulting unit test error
        if out:
            out = out.strip()
            if (out[0] == 'o') or (out[0] == 'O'):
                raise exception.VolumeIsBusy(volume_name=volume['name'])

        self._delete_volume(volume, volume['size'])

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        orig_lv_name = "%s/%s" % (FLAGS.volume_group, snapshot['volume_name'])
        self._try_execute('lvcreate', '-L',
                          self._sizestr(snapshot['volume_size']),
                          '--name', self._escape_snapshot(snapshot['name']),
                          '--snapshot', orig_lv_name, run_as_root=True)

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

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        raise NotImplementedError()

    def initialize_connection(self, volume, connector):
        """Allow connection to connector and return connection info."""
        raise NotImplementedError()

    def terminate_connection(self, volume, connector):
        """Disallow connection from connector"""
        raise NotImplementedError()

    def attach_volume(self, context, volume_id, instance_uuid, mountpoint):
        """ Callback for volume attached to instance."""
        pass

    def detach_volume(self, context, volume_id):
        """ Callback for volume detached."""
        pass

    def get_volume_stats(self, refresh=False):
        """Return the current state of the volume service. If 'refresh' is
           True, run the update first."""
        return None

    def do_setup(self, context):
        """Any initialization the volume driver does while starting"""
        pass

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        raise NotImplementedError()

    def copy_volume_to_image(self, context, volume, image_service, image_id):
        """Copy the volume to the specified image."""
        raise NotImplementedError()

    def clone_image(self, volume, image_location):
        """Create a volume efficiently from an existing image.

        image_location is a string whose format depends on the
        image service backend in use. The driver should use it
        to determine whether cloning is possible.

        Returns a boolean indicating whether cloning occurred
        """
        return False


class ISCSIDriver(VolumeDriver):
    """Executes commands relating to ISCSI volumes.

    We make use of model provider properties as follows:

    ``provider_location``
      if present, contains the iSCSI target information in the same
      format as an ietadm discovery
      i.e. '<ip>:<port>,<portal> <target IQN>'

    ``provider_auth``
      if present, contains a space-separated triple:
      '<auth method> <auth username> <auth password>'.
      `CHAP` is the only auth_method in use at the moment.
    """

    def __init__(self, *args, **kwargs):
        self.tgtadm = iscsi.get_target_admin()
        super(ISCSIDriver, self).__init__(*args, **kwargs)

    def set_execute(self, execute):
        super(ISCSIDriver, self).set_execute(execute)
        self.tgtadm.set_execute(execute)

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        # NOTE(jdg): tgtadm doesn't use the iscsi_targets table
        # TODO(jdg): In the future move all of the dependent stuff into the
        # cooresponding target admin class
        if not isinstance(self.tgtadm, iscsi.TgtAdm):
            try:
                iscsi_target = self.db.volume_get_iscsi_target_num(context,
                                                               volume['id'])
            except exception.NotFound:
                LOG.info(_("Skipping ensure_export. No iscsi_target "
                           "provisioned for volume: %s"), volume['id'])
                return
        else:
            iscsi_target = 1  # dummy value when using TgtAdm

        # Check for https://bugs.launchpad.net/nova/+bug/1065702
        old_name = None
        volume_name = volume['name']
        if (volume['provider_location'] is not None and
            volume['name'] not in volume['provider_location']):

            msg = _('Detected inconsistency in provider_location id')
            LOG.debug(msg)
            old_name = self._fix_id_migration(context, volume)
            if 'in-use' in volume['status']:
                volume_name = old_name
                old_name = None

        iscsi_name = "%s%s" % (FLAGS.iscsi_target_prefix, volume_name)
        volume_path = "/dev/%s/%s" % (FLAGS.volume_group, volume_name)

        # NOTE(jdg): For TgtAdm case iscsi_name is the ONLY param we need
        # should clean this all up at some point in the future
        self.tgtadm.create_iscsi_target(iscsi_name, iscsi_target,
                                        0, volume_path,
                                        check_exit_code=False,
                                        old_name=old_name)

    def _fix_id_migration(self, context, volume):
        """Fix provider_location and dev files to address bug 1065702.

        For volumes that the provider_location has NOT been updated
        and are not currently in-use we'll create a new iscsi target
        and remove the persist file.

        If the volume is in-use, we'll just stick with the old name
        and when detach is called we'll feed back into ensure_export
        again if necessary and fix things up then.

        Details at: https://bugs.launchpad.net/nova/+bug/1065702
        """

        model_update = {}
        pattern = re.compile(r":|\s")
        fields = pattern.split(volume['provider_location'])
        old_name = fields[3]

        volume['provider_location'] = \
            volume['provider_location'].replace(old_name, volume['name'])
        model_update['provider_location'] = volume['provider_location']

        self.db.volume_update(context, volume['id'], model_update)

        start = os.getcwd()
        os.chdir('/dev/%s' % FLAGS.volume_group)

        try:
            (out, err) = self._execute('readlink', old_name)
        except exception.ProcessExecutionError:
            link_path = '/dev/%s/%s' % (FLAGS.volume_group, old_name)
            LOG.debug(_('Symbolic link %s not found') % link_path)
            os.chdir(start)
            return

        rel_path = out.rstrip()
        self._execute('ln',
                      '-s',
                      rel_path, volume['name'],
                      run_as_root=True)
        os.chdir(start)
        return old_name

    def _ensure_iscsi_targets(self, context, host):
        """Ensure that target ids have been created in datastore."""
        # NOTE(jdg): tgtadm doesn't use the iscsi_targets table
        # TODO(jdg): In the future move all of the dependent stuff into the
        # cooresponding target admin class
        if not isinstance(self.tgtadm, iscsi.TgtAdm):
            host_iscsi_targets = self.db.iscsi_target_count_by_host(context,
                                                                    host)
            if host_iscsi_targets >= FLAGS.iscsi_num_targets:
                return

            # NOTE(vish): Target ids start at 1, not 0.
            for target_num in xrange(1, FLAGS.iscsi_num_targets + 1):
                target = {'host': host, 'target_num': target_num}
                self.db.iscsi_target_create_safe(context, target)

    def create_export(self, context, volume):
        """Creates an export for a logical volume."""

        iscsi_name = "%s%s" % (FLAGS.iscsi_target_prefix, volume['name'])
        volume_path = "/dev/%s/%s" % (FLAGS.volume_group, volume['name'])

        model_update = {}

        # TODO(jdg): In the future move all of the dependent stuff into the
        # cooresponding target admin class
        if not isinstance(self.tgtadm, iscsi.TgtAdm):
            lun = 0
            self._ensure_iscsi_targets(context, volume['host'])
            iscsi_target = self.db.volume_allocate_iscsi_target(context,
                                                                volume['id'],
                                                                volume['host'])
        else:
            lun = 1  # For tgtadm the controller is lun 0, dev starts at lun 1
            iscsi_target = 0  # NOTE(jdg): Not used by tgtadm

        # NOTE(jdg): For TgtAdm case iscsi_name is the ONLY param we need
        # should clean this all up at some point in the future
        tid = self.tgtadm.create_iscsi_target(iscsi_name,
                                              iscsi_target,
                                              0,
                                              volume_path)
        model_update['provider_location'] = _iscsi_location(
            FLAGS.iscsi_ip_address, tid, iscsi_name, lun)
        return model_update

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""

        # NOTE(jdg): tgtadm doesn't use the iscsi_targets table
        # TODO(jdg): In the future move all of the dependent stuff into the
        # cooresponding target admin class
        if not isinstance(self.tgtadm, iscsi.TgtAdm):
            try:
                iscsi_target = self.db.volume_get_iscsi_target_num(context,
                                                               volume['id'])
            except exception.NotFound:
                LOG.info(_("Skipping remove_export. No iscsi_target "
                           "provisioned for volume: %s"), volume['id'])
                return
        else:
            iscsi_target = 0

        try:

            # NOTE: provider_location may be unset if the volume hasn't
            # been exported
            location = volume['provider_location'].split(' ')
            iqn = location[1]

            # ietadm show will exit with an error
            # this export has already been removed
            self.tgtadm.show_target(iscsi_target, iqn=iqn)
        except Exception as e:
            LOG.info(_("Skipping remove_export. No iscsi_target "
                       "is presently exported for volume: %s"), volume['id'])
            return

        self.tgtadm.remove_iscsi_target(iscsi_target, 0, volume['id'])

    def _do_iscsi_discovery(self, volume):
        #TODO(justinsb): Deprecate discovery and use stored info
        #NOTE(justinsb): Discovery won't work with CHAP-secured targets (?)
        LOG.warn(_("ISCSI provider_location not stored, using discovery"))

        volume_name = volume['name']

        (out, _err) = self._execute('iscsiadm', '-m', 'discovery',
                                    '-t', 'sendtargets', '-p', volume['host'],
                                    run_as_root=True)
        for target in out.splitlines():
            if FLAGS.iscsi_ip_address in target and volume_name in target:
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

        :target_lun:    the lun of the iSCSI target

        :volume_id:    the id of the volume (currently used by xen)

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
                raise exception.InvalidVolume(_("Could not find iSCSI export "
                                                " for volume %s") %
                                              (volume['name']))

            LOG.debug(_("ISCSI Discovery: Found %s") % (location))
            properties['target_discovered'] = True

        results = location.split(" ")
        properties['target_portal'] = results[0].split(",")[0]
        properties['target_iqn'] = results[1]
        try:
            properties['target_lun'] = int(results[2])
        except (IndexError, ValueError):
            if FLAGS.iscsi_helper == 'tgtadm':
                properties['target_lun'] = 1
            else:
                properties['target_lun'] = 0

        properties['volume_id'] = volume['id']

        auth = volume['provider_auth']
        if auth:
            (auth_method, auth_username, auth_secret) = auth.split()

            properties['auth_method'] = auth_method
            properties['auth_username'] = auth_username
            properties['auth_password'] = auth_secret

        return properties

    def _run_iscsiadm(self, iscsi_properties, iscsi_command):
        (out, err) = self._execute('iscsiadm', '-m', 'node', '-T',
                                   iscsi_properties['target_iqn'],
                                   '-p', iscsi_properties['target_portal'],
                                   *iscsi_command, run_as_root=True)
        LOG.debug("iscsiadm %s: stdout=%s stderr=%s" %
                  (iscsi_command, out, err))
        return (out, err)

    def _iscsiadm_update(self, iscsi_properties, property_key, property_value):
        iscsi_command = ('--op', 'update', '-n', property_key,
                         '-v', property_value)
        return self._run_iscsiadm(iscsi_properties, iscsi_command)

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info.

        The iscsi driver returns a driver_volume_type of 'iscsi'.
        The format of the driver data is defined in _get_iscsi_properties.
        Example return value::

            {
                'driver_volume_type': 'iscsi'
                'data': {
                    'target_discovered': True,
                    'target_iqn': 'iqn.2010-10.org.openstack:volume-00000001',
                    'target_portal': '127.0.0.0.1:3260',
                    'volume_id': 1,
                }
            }

        """

        iscsi_properties = self._get_iscsi_properties(volume)
        return {
            'driver_volume_type': 'iscsi',
            'data': iscsi_properties
        }

    def terminate_connection(self, volume, connector):
        pass

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        vol_uuid_file = 'volume-%s' % volume_id
        volume_path = os.path.join(FLAGS.volumes_dir, vol_uuid_file)
        if os.path.isfile(volume_path):
            iqn = '%s%s' % (FLAGS.iscsi_target_prefix,
                            vol_uuid_file)
        else:
            raise exception.PersistentVolumeFileNotFound(volume_id=volume_id)

        # TODO(jdg): In the future move all of the dependent stuff into the
        # cooresponding target admin class
        if not isinstance(self.tgtadm, iscsi.TgtAdm):
            tid = self.db.volume_get_iscsi_target_num(context, volume_id)
        else:
            tid = 0

        try:
            self.tgtadm.show_target(tid, iqn=iqn)
        except exception.ProcessExecutionError, e:
            # Instances remount read-only in this case.
            # /etc/init.d/iscsitarget restart and rebooting nova-volume
            # is better since ensure_export() works at boot time.
            LOG.error(_("Cannot confirm exported volume "
                        "id:%(volume_id)s.") % locals())
            raise

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        volume_path = self.local_path(volume)
        with utils.temporary_chown(volume_path):
            with utils.file_open(volume_path, "wb") as image_file:
                image_service.download(context, image_id, image_file)

    def copy_volume_to_image(self, context, volume, image_service, image_id):
        """Copy the volume to the specified image."""
        volume_path = self.local_path(volume)
        with utils.temporary_chown(volume_path):
            with utils.file_open(volume_path) as volume_file:
                image_service.update(context, image_id, {}, volume_file)


class FakeISCSIDriver(ISCSIDriver):
    """Logs calls instead of executing."""
    def __init__(self, *args, **kwargs):
        super(FakeISCSIDriver, self).__init__(execute=self.fake_execute,
                                              *args, **kwargs)

    def check_for_setup_error(self):
        """No setup necessary in fake mode."""
        pass

    def initialize_connection(self, volume, connector):
        return {
            'driver_volume_type': 'iscsi',
            'data': {}
        }

    def terminate_connection(self, volume, connector):
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
            exception_message = (_("rbd has no pool %s") %
                                    FLAGS.rbd_pool)
            raise exception.VolumeBackendAPIException(data=exception_message)

    def _supports_layering(self):
        stdout, _ = self._execute('rbd', '--help')
        return 'clone' in stdout

    def create_volume(self, volume):
        """Creates a logical volume."""
        if int(volume['size']) == 0:
            size = 100
        else:
            size = int(volume['size']) * 1024
        args = ['rbd', 'create',
                '--pool', FLAGS.rbd_pool,
                '--size', size,
                volume['name']]
        if self._supports_layering():
            args += ['--new-format']
        self._try_execute(*args)

    def _clone(self, volume, src_pool, src_image, src_snap):
        self._try_execute('rbd', 'clone',
                          '--pool', src_pool,
                          '--image', src_image,
                          '--snap', src_snap,
                          '--dest-pool', FLAGS.rbd_pool,
                          '--dest', volume['name'])

    def _resize(self, volume):
        size = int(volume['size']) * 1024
        self._try_execute('rbd', 'resize',
                          '--pool', FLAGS.rbd_pool,
                          '--image', volume['name'],
                          '--size', size)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        self._clone(volume, FLAGS.rbd_pool,
                    snapshot['volume_name'], snapshot['name'])
        if int(volume['size']):
            self._resize(volume)

    def delete_volume(self, volume):
        """Deletes a logical volume."""
        stdout, _ = self._execute('rbd', 'snap', 'ls',
                                  '--pool', FLAGS.rbd_pool,
                                  volume['name'])
        if stdout.count('\n') > 1:
            raise exception.VolumeIsBusy(volume_name=volume['name'])
        self._try_execute('rbd', 'rm',
                          '--pool', FLAGS.rbd_pool,
                          volume['name'])

    def create_snapshot(self, snapshot):
        """Creates an rbd snapshot"""
        self._try_execute('rbd', 'snap', 'create',
                          '--pool', FLAGS.rbd_pool,
                          '--snap', snapshot['name'],
                          snapshot['volume_name'])
        if self._supports_layering():
            self._try_execute('rbd', 'snap', 'protect',
                              '--pool', FLAGS.rbd_pool,
                              '--snap', snapshot['name'],
                              snapshot['volume_name'])

    def delete_snapshot(self, snapshot):
        """Deletes an rbd snapshot"""
        if self._supports_layering():
            try:
                self._try_execute('rbd', 'snap', 'unprotect',
                                  '--pool', FLAGS.rbd_pool,
                                  '--snap', snapshot['name'],
                                  snapshot['volume_name'])
            except exception.ProcessExecutionError:
                raise exception.SnapshotIsBusy(snapshot_name=snapshot['name'])
        self._try_execute('rbd', 'snap', 'rm',
                          '--pool', FLAGS.rbd_pool,
                          '--snap', snapshot['name'],
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

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        pass

    def initialize_connection(self, volume, connector):
        return {
            'driver_volume_type': 'rbd',
            'data': {
                'name': '%s/%s' % (FLAGS.rbd_pool, volume['name']),
                'auth_enabled': FLAGS.rbd_secret_uuid is not None,
                'auth_username': FLAGS.rbd_user,
                'secret_type': 'ceph',
                'secret_uuid': FLAGS.rbd_secret_uuid,
            }
        }

    def terminate_connection(self, volume, connector):
        pass

    def _parse_location(self, location):
        prefix = 'rbd://'
        if not location.startswith(prefix):
            reason = _('Image %s is not stored in rbd') % location
            raise exception.ImageUnacceptable(reason)
        pieces = map(urllib.unquote, location[len(prefix):].split('/'))
        if any(map(lambda p: p == '', pieces)):
            reason = _('Image %s has blank components') % location
            raise exception.ImageUnacceptable(reason)
        if len(pieces) != 4:
            reason = _('Image %s is not an rbd snapshot') % location
            raise exception.ImageUnacceptable(reason)
        return pieces

    def _get_fsid(self):
        stdout, _ = self._execute('ceph', 'fsid')
        return stdout.rstrip('\n')

    def _is_cloneable(self, image_location):
        try:
            fsid, pool, image, snapshot = self._parse_location(image_location)
        except exception.ImageUnacceptable:
            return False

        if self._get_fsid() != fsid:
            reason = _('%s is in a different ceph cluster') % image_location
            LOG.debug(reason)
            return False

        # check that we can read the image
        try:
            self._execute('rbd', 'info',
                          '--pool', pool,
                          '--image', image,
                          '--snap', snapshot)
        except exception.ProcessExecutionError:
            LOG.debug(_('Unable to read image %s') % image_location)
            return False

        return True

    def clone_image(self, volume, image_location):
        if image_location is None or not self._is_cloneable(image_location):
            return False
        _, pool, image, snapshot = self._parse_location(image_location)
        self._clone(volume, pool, image, snapshot)
        self._resize(volume)
        return True

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        # TODO(jdurgin): replace with librbd
        # this is a temporary hack, since rewriting this driver
        # to use librbd would take too long
        if FLAGS.volume_tmp_dir and not os.path.exists(FLAGS.volume_tmp_dir):
            os.makedirs(FLAGS.volume_tmp_dir)

        with tempfile.NamedTemporaryFile(dir=FLAGS.volume_tmp_dir) as tmp:
            image_service.download(context, image_id, tmp)
            # import creates the image, so we must remove it first
            self._try_execute('rbd', 'rm',
                              '--pool', FLAGS.rbd_pool,
                              volume['name'])
            self._try_execute('rbd', 'import',
                              '--pool', FLAGS.rbd_pool,
                              tmp.name, volume['name'])


class SheepdogDriver(VolumeDriver):
    """Executes commands relating to Sheepdog Volumes"""

    def check_for_setup_error(self):
        """Returns an error if prerequisites aren't met"""
        try:
            #NOTE(francois-charlier) Since 0.24 'collie cluster info -r'
            #  gives short output, but for compatibility reason we won't
            #  use it and just check if 'running' is in the output.
            (out, err) = self._execute('collie', 'cluster', 'info')
            if not 'running' in out.split():
                exception_message = _("Sheepdog is not working: %s") % out
                raise exception.VolumeBackendAPIException(
                                                data=exception_message)

        except exception.ProcessExecutionError:
            exception_message = _("Sheepdog is not working")
            raise exception.NovaException(data=exception_message)

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

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        pass

    def initialize_connection(self, volume, connector):
        return {
            'driver_volume_type': 'sheepdog',
            'data': {
                'name': volume['name']
            }
        }

    def terminate_connection(self, volume, connector):
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

    def initialize_connection(self, volume, connector):
        self.log_action('initialize_connection', volume)

    def terminate_connection(self, volume, connector):
        self.log_action('terminate_connection', volume)

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


def _iscsi_location(ip, target, iqn, lun=None):
    return "%s:%s,%s %s %s" % (ip, FLAGS.iscsi_port, target, iqn, lun)
