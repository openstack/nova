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
flags.DEFINE_string('iscsi_ip_prefix', '127.0',
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

    def _try_execute(self, command):
        # NOTE(vish): Volume commands can partially fail due to timing, but
        #             running them a second time on failure will usually
        #             recover nicely.
        tries = 0
        while True:
            try:
                self._execute(command)
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
        out, err = self._execute("sudo vgs --noheadings -o name")
        volume_groups = out.split()
        if not FLAGS.volume_group in volume_groups:
            raise exception.Error(_("volume group %s doesn't exist")
                                  % FLAGS.volume_group)

    def create_volume(self, volume):
        """Creates a logical volume."""
        if int(volume['size']) == 0:
            sizestr = '100M'
        else:
            sizestr = '%sG' % volume['size']
        self._try_execute("sudo lvcreate -L %s -n %s %s" %
                          (sizestr,
                           volume['name'],
                           FLAGS.volume_group))

    def delete_volume(self, volume):
        """Deletes a logical volume."""
        self._try_execute("sudo lvremove -f %s/%s" %
                          (FLAGS.volume_group,
                           volume['name']))

    def local_path(self, volume):
        # NOTE(vish): stops deprecation warning
        escaped_group = FLAGS.volume_group.replace('-', '--')
        escaped_name = volume['name'].replace('-', '--')
        return "/dev/mapper/%s-%s" % (escaped_group, escaped_name)

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        raise NotImplementedError()

    def create_export(self, context, volume):
        """Exports the volume."""
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
                "sudo vblade-persist setup %s %s %s /dev/%s/%s" %
                (shelf_id,
                 blade_id,
                 FLAGS.aoe_eth_dev,
                 FLAGS.volume_group,
                 volume['name']))
        # NOTE(vish): The standard _try_execute does not work here
        #             because these methods throw errors if other
        #             volumes on this host are in the process of
        #             being created.  The good news is the command
        #             still works for the other volumes, so we
        #             just wait a bit for the current volume to
        #             be ready and ignore any errors.
        time.sleep(2)
        self._execute("sudo vblade-persist auto all",
                      check_exit_code=False)
        self._execute("sudo vblade-persist start all",
                      check_exit_code=False)

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        (shelf_id,
         blade_id) = self.db.volume_get_shelf_and_blade(context,
                                                        volume['id'])
        self._try_execute("sudo vblade-persist stop %s %s" %
                          (shelf_id, blade_id))
        self._try_execute("sudo vblade-persist destroy %s %s" %
                          (shelf_id, blade_id))

    def discover_volume(self, context, volume):
        """Discover volume on a remote host."""
        self._execute("sudo aoe-discover")
        self._execute("sudo aoe-stat", check_exit_code=False)
        shelf_id, blade_id = self.db.volume_get_shelf_and_blade(context,
                                                                volume['id'])
        return "/dev/etherd/e%s.%s" % (shelf_id, blade_id)

    def undiscover_volume(self, _volume):
        """Undiscover volume on a remote host."""
        pass

    def check_for_export(self, context, volume_id):
        """Make sure whether volume is exported."""
        (shelf_id,
         blade_id) = self.db.volume_get_shelf_and_blade(context,
                                                        volume_id)
        (out, _err) = self._execute("sudo vblade-persist ls --no-header")
        exists = False
        for line in out.split('\n'):
            param = line.split(' ')
            if len(param) == 6 and param[0] == str(shelf_id) \
                    and param[1] == str(blade_id) and param[-1] == "run":
                exists = True
                break
        if not exists:
            logging.warning(_("vblade process for e%s.%s isn't running.")
                            % (shelf_id, blade_id))


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
    """Executes commands relating to ISCSI volumes."""

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        iscsi_target = self.db.volume_get_iscsi_target_num(context,
                                                           volume['id'])
        iscsi_name = "%s%s" % (FLAGS.iscsi_target_prefix, volume['name'])
        volume_path = "/dev/%s/%s" % (FLAGS.volume_group, volume['name'])
        self._sync_exec("sudo ietadm --op new "
                        "--tid=%s --params Name=%s" %
                        (iscsi_target, iscsi_name),
                        check_exit_code=False)
        self._sync_exec("sudo ietadm --op new --tid=%s "
                        "--lun=0 --params Path=%s,Type=fileio" %
                        (iscsi_target, volume_path),
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
        self._execute("sudo ietadm --op new "
                      "--tid=%s --params Name=%s" %
                      (iscsi_target, iscsi_name))
        self._execute("sudo ietadm --op new --tid=%s "
                      "--lun=0 --params Path=%s,Type=fileio" %
                      (iscsi_target, volume_path))

    def remove_export(self, context, volume):
        """Removes an export for a logical volume."""
        iscsi_target = self.db.volume_get_iscsi_target_num(context,
                                                           volume['id'])
        self._execute("sudo ietadm --op delete --tid=%s "
                      "--lun=0" % iscsi_target)
        self._execute("sudo ietadm --op delete --tid=%s" %
                      iscsi_target)

    def _get_name_and_portal(self, volume_name, host):
        """Gets iscsi name and portal from volume name and host."""
        (out, _err) = self._execute("sudo iscsiadm -m discovery -t "
                                    "sendtargets -p %s" % host)
        for target in out.splitlines():
            if FLAGS.iscsi_ip_prefix in target and volume_name in target:
                (location, _sep, iscsi_name) = target.partition(" ")
                break
        iscsi_portal = location.split(",")[0]
        return (iscsi_name, iscsi_portal)

    def discover_volume(self, _context, volume):
        """Discover volume on a remote host."""
        iscsi_name, iscsi_portal = self._get_name_and_portal(volume['name'],
                                                             volume['host'])
        self._execute("sudo iscsiadm -m node -T %s -p %s --login" %
                      (iscsi_name, iscsi_portal))
        self._execute("sudo iscsiadm -m node -T %s -p %s --op update "
                      "-n node.startup -v automatic" %
                      (iscsi_name, iscsi_portal))
        return "/dev/iscsi/%s" % volume['name']

    def undiscover_volume(self, volume):
        """Undiscover volume on a remote host."""
        iscsi_name, iscsi_portal = self._get_name_and_portal(volume['name'],
                                                             volume['host'])
        self._execute("sudo iscsiadm -m node -T %s -p %s --op update "
                      "-n node.startup -v manual" %
                      (iscsi_name, iscsi_portal))
        self._execute("sudo iscsiadm -m node -T %s -p %s --logout " %
                      (iscsi_name, iscsi_portal))
        self._execute("sudo iscsiadm -m node --op delete "
                      "--targetname %s" % iscsi_name)


class FakeISCSIDriver(ISCSIDriver):
    """Logs calls instead of executing."""
    def __init__(self, *args, **kwargs):
        super(FakeISCSIDriver, self).__init__(execute=self.fake_execute,
                                              sync_exec=self.fake_execute,
                                              *args, **kwargs)

    def check_for_setup_error(self):
        """No setup necessary in fake mode."""
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
        (stdout, stderr) = self._execute("rados lspools")
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
        self._try_execute("rbd --pool %s --size %d create %s" %
                          (FLAGS.rbd_pool,
                           size,
                           volume['name']))

    def delete_volume(self, volume):
        """Deletes a logical volume."""
        self._try_execute("rbd --pool %s rm %s" %
                          (FLAGS.rbd_pool,
                           volume['name']))

    def local_path(self, volume):
        """Returns the path of the rbd volume."""
        # This is the same as the remote path
        # since qemu accesses it directly.
        return self.discover_volume(volume)

    def ensure_export(self, context, volume):
        """Synchronously recreates an export for a logical volume."""
        pass

    def create_export(self, context, volume):
        """Exports the volume"""
        pass

    def remove_export(self, context, volume):
        """Removes an export for a logical volume"""
        pass

    def discover_volume(self, volume):
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
            (out, err) = self._execute("collie cluster info")
            if not out.startswith('running'):
                raise exception.Error(_("Sheepdog is not working: %s") % out)
        except exception.ProcessExecutionError:
            raise exception.Error(_("Sheepdog is not working"))

    def create_volume(self, volume):
        """Creates a sheepdog volume"""
        if int(volume['size']) == 0:
            sizestr = '100M'
        else:
            sizestr = '%sG' % volume['size']
        self._try_execute("qemu-img create sheepdog:%s %s" %
                          (volume['name'], sizestr))

    def delete_volume(self, volume):
        """Deletes a logical volume"""
        self._try_execute("collie vdi delete %s" % volume['name'])

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

    def discover_volume(self, volume):
        """Discover volume on a remote host"""
        return "sheepdog:%s" % volume['name']

    def undiscover_volume(self, volume):
        """Undiscover volume on a remote host"""
        pass
