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
Volume manager manages creating, attaching, detaching, and persistent storage.

Persistant storage volumes keep their state independent of instances.  You can
attach to an instance, terminate the instance, spawn a new instance (even
one from a different image) and re-attach the volume with the same data
intact.

**Related Flags**

:volume_topic:  What :mod:`rpc` topic to listen to (default: `volume`).
:volume_manager:  The module name of a class derived from
                  :class:`manager.Manager` (default:
                  :class:`nova.volume.manager.AOEManager`).
:storage_availability_zone:  Defaults to `nova`.
:volume_driver:  Used by :class:`AOEManager`.  Defaults to
                 :class:`nova.volume.driver.AOEDriver`.
:num_shelves:  Number of shelves for AoE (default: 100).
:num_blades:  Number of vblades per shelf to allocate AoE storage from
              (default: 16).
:volume_group:  Name of the group that will contain exported volumes (default:
                `nova-volumes`)
:aoe_eth_dev:  Device name the volumes will be exported on (default: `eth0`).
:num_shell_tries:  Number of times to attempt to run AoE commands (default: 3)

"""


from nova import context
from nova import exception
from nova import flags
from nova import log as logging
from nova import manager
from nova import rpc
from nova import utils
from nova.volume import volume_types


LOG = logging.getLogger('nova.volume.manager')
FLAGS = flags.FLAGS
flags.DEFINE_string('storage_availability_zone',
                    'nova',
                    'availability zone of this service')
flags.DEFINE_string('volume_driver', 'nova.volume.driver.ISCSIDriver',
                    'Driver to use for volume creation')
flags.DEFINE_boolean('use_local_volumes', True,
                     'if True, will not discover local volumes')
flags.DEFINE_boolean('volume_force_update_capabilities', False,
                     'if True will force update capabilities on each check')


class VolumeManager(manager.SchedulerDependentManager):
    """Manages attachable block storage devices."""
    def __init__(self, volume_driver=None, *args, **kwargs):
        """Load the driver from the one specified in args, or from flags."""
        if not volume_driver:
            volume_driver = FLAGS.volume_driver
        self.driver = utils.import_object(volume_driver)
        super(VolumeManager, self).__init__(service_name='volume',
                                                    *args, **kwargs)
        # NOTE(vish): Implementation specific db handling is done
        #             by the driver.
        self.driver.db = self.db
        self._last_volume_stats = []

    def init_host(self):
        """Do any initialization that needs to be run if this is a
           standalone service."""
        self.driver.check_for_setup_error()
        ctxt = context.get_admin_context()
        volumes = self.db.volume_get_all_by_host(ctxt, self.host)
        LOG.debug(_("Re-exporting %s volumes"), len(volumes))
        for volume in volumes:
            if volume['status'] in ['available', 'in-use']:
                self.driver.ensure_export(ctxt, volume)
            else:
                LOG.info(_("volume %s: skipping export"), volume['name'])

    def create_volume(self, context, volume_id, snapshot_id=None):
        """Creates and exports the volume."""
        context = context.elevated()
        volume_ref = self.db.volume_get(context, volume_id)
        LOG.info(_("volume %s: creating"), volume_ref['name'])

        self.db.volume_update(context,
                              volume_id,
                              {'host': self.host})
        # NOTE(vish): so we don't have to get volume from db again
        #             before passing it to the driver.
        volume_ref['host'] = self.host

        try:
            vol_name = volume_ref['name']
            vol_size = volume_ref['size']
            LOG.debug(_("volume %(vol_name)s: creating lv of"
                    " size %(vol_size)sG") % locals())
            if snapshot_id == None:
                model_update = self.driver.create_volume(volume_ref)
            else:
                snapshot_ref = self.db.snapshot_get(context, snapshot_id)
                model_update = self.driver.create_volume_from_snapshot(
                    volume_ref,
                    snapshot_ref)
            if model_update:
                self.db.volume_update(context, volume_ref['id'], model_update)

            LOG.debug(_("volume %s: creating export"), volume_ref['name'])
            model_update = self.driver.create_export(context, volume_ref)
            if model_update:
                self.db.volume_update(context, volume_ref['id'], model_update)
        except Exception:
            with utils.save_and_reraise_exception():
                self.db.volume_update(context,
                                      volume_ref['id'], {'status': 'error'})
                self._notify_vsa(context, volume_ref, 'error')

        now = utils.utcnow()
        self.db.volume_update(context,
                              volume_ref['id'], {'status': 'available',
                                                 'launched_at': now})
        LOG.debug(_("volume %s: created successfully"), volume_ref['name'])
        self._notify_vsa(context, volume_ref, 'available')
        self._reset_stats()
        return volume_id

    def _notify_vsa(self, context, volume_ref, status):
        if volume_ref['volume_type_id'] is None:
            return

        if volume_types.is_vsa_drive(volume_ref['volume_type_id']):
            vsa_id = None
            for i in volume_ref.get('volume_metadata'):
                if i['key'] == 'to_vsa_id':
                    vsa_id = int(i['value'])
                    break

            if vsa_id:
                rpc.cast(context,
                         FLAGS.vsa_topic,
                         {"method": "vsa_volume_created",
                          "args": {"vol_id": volume_ref['id'],
                                   "vsa_id": vsa_id,
                                   "status": status}})

    def delete_volume(self, context, volume_id):
        """Deletes and unexports volume."""
        context = context.elevated()
        volume_ref = self.db.volume_get(context, volume_id)
        if volume_ref['attach_status'] == "attached":
            raise exception.Error(_("Volume is still attached"))
        if volume_ref['host'] != self.host:
            raise exception.Error(_("Volume is not local to this node"))

        self._reset_stats()
        try:
            LOG.debug(_("volume %s: removing export"), volume_ref['name'])
            self.driver.remove_export(context, volume_ref)
            LOG.debug(_("volume %s: deleting"), volume_ref['name'])
            self.driver.delete_volume(volume_ref)
        except exception.VolumeIsBusy, e:
            LOG.debug(_("volume %s: volume is busy"), volume_ref['name'])
            self.driver.ensure_export(context, volume_ref)
            self.db.volume_update(context, volume_ref['id'],
                                  {'status': 'available'})
            return True
        except Exception:
            with utils.save_and_reraise_exception():
                self.db.volume_update(context,
                                      volume_ref['id'],
                                      {'status': 'error_deleting'})

        self.db.volume_destroy(context, volume_id)
        LOG.debug(_("volume %s: deleted successfully"), volume_ref['name'])
        return True

    def create_snapshot(self, context, volume_id, snapshot_id):
        """Creates and exports the snapshot."""
        context = context.elevated()
        snapshot_ref = self.db.snapshot_get(context, snapshot_id)
        LOG.info(_("snapshot %s: creating"), snapshot_ref['name'])

        try:
            snap_name = snapshot_ref['name']
            LOG.debug(_("snapshot %(snap_name)s: creating") % locals())
            model_update = self.driver.create_snapshot(snapshot_ref)
            if model_update:
                self.db.snapshot_update(context, snapshot_ref['id'],
                                        model_update)

        except Exception:
            with utils.save_and_reraise_exception():
                self.db.snapshot_update(context,
                                        snapshot_ref['id'],
                                        {'status': 'error'})

        self.db.snapshot_update(context,
                                snapshot_ref['id'], {'status': 'available',
                                                     'progress': '100%'})
        LOG.debug(_("snapshot %s: created successfully"), snapshot_ref['name'])
        return snapshot_id

    def delete_snapshot(self, context, snapshot_id):
        """Deletes and unexports snapshot."""
        context = context.elevated()
        snapshot_ref = self.db.snapshot_get(context, snapshot_id)

        try:
            LOG.debug(_("snapshot %s: deleting"), snapshot_ref['name'])
            self.driver.delete_snapshot(snapshot_ref)
        except Exception:
            with utils.save_and_reraise_exception():
                self.db.snapshot_update(context,
                                        snapshot_ref['id'],
                                        {'status': 'error_deleting'})

        self.db.snapshot_destroy(context, snapshot_id)
        LOG.debug(_("snapshot %s: deleted successfully"), snapshot_ref['name'])
        return True

    def setup_compute_volume(self, context, volume_id):
        """Setup remote volume on compute host.

        Returns path to device."""
        context = context.elevated()
        volume_ref = self.db.volume_get(context, volume_id)
        if volume_ref['host'] == self.host and FLAGS.use_local_volumes:
            path = self.driver.local_path(volume_ref)
        else:
            path = self.driver.discover_volume(context, volume_ref)
        return path

    def remove_compute_volume(self, context, volume_id):
        """Remove remote volume on compute host."""
        context = context.elevated()
        volume_ref = self.db.volume_get(context, volume_id)
        if volume_ref['host'] == self.host and FLAGS.use_local_volumes:
            return True
        else:
            self.driver.undiscover_volume(volume_ref)

    def check_for_export(self, context, instance_id):
        """Make sure whether volume is exported."""
        instance_ref = self.db.instance_get(context, instance_id)
        for volume in instance_ref['volumes']:
            self.driver.check_for_export(context, volume['id'])

    def periodic_tasks(self, context=None):
        """Tasks to be run at a periodic interval."""

        error_list = []
        try:
            self._report_driver_status()
        except Exception as ex:
            LOG.warning(_("Error during report_driver_status(): %s"),
                        unicode(ex))
            error_list.append(ex)

        super(VolumeManager, self).periodic_tasks(context)

        return error_list

    def _volume_stats_changed(self, stat1, stat2):
        if FLAGS.volume_force_update_capabilities:
            return True
        if len(stat1) != len(stat2):
            return True
        for (k, v) in stat1.iteritems():
            if (k, v) not in stat2.iteritems():
                return True
        return False

    def _report_driver_status(self):
        volume_stats = self.driver.get_volume_stats(refresh=True)
        if volume_stats:
            LOG.info(_("Checking volume capabilities"))

            if self._volume_stats_changed(self._last_volume_stats,
                                          volume_stats):
                LOG.info(_("New capabilities found: %s"), volume_stats)
                self._last_volume_stats = volume_stats

                # This will grab info about the host and queue it
                # to be sent to the Schedulers.
                self.update_service_capabilities(self._last_volume_stats)
            else:
                # avoid repeating fanouts
                self.update_service_capabilities(None)

    def _reset_stats(self):
        LOG.info(_("Clear capabilities"))
        self._last_volume_stats = []

    def notification(self, context, event):
        LOG.info(_("Notification {%s} received"), event)
        self._reset_stats()
