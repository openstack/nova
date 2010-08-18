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
Nova Storage manages creating, attaching, detaching, and
destroying persistent storage volumes, ala EBS.
Currently uses Ata-over-Ethernet.
"""

import logging

from twisted.internet import defer

from nova import exception
from nova import flags
from nova import models
from nova import process
from nova import service
from nova import utils
from nova import validate


FLAGS = flags.FLAGS
flags.DEFINE_string('storage_dev', '/dev/sdb',
                    'Physical device to use for volumes')
flags.DEFINE_string('volume_group', 'nova-volumes',
                    'Name for the VG that will contain exported volumes')
flags.DEFINE_string('aoe_eth_dev', 'eth0',
                    'Which device to export the volumes on')
flags.DEFINE_string('aoe_export_dir',
                    '/var/lib/vblade-persist/vblades',
                    'AoE directory where exports are created')
flags.DEFINE_integer('blades_per_shelf',
                    16,
                    'Number of AoE blades per shelf')
flags.DEFINE_string('storage_availability_zone',
                    'nova',
                    'availability zone of this service')
flags.DEFINE_boolean('fake_storage', False,
                     'Should we make real storage volumes to attach?')


class NoMoreBlades(exception.Error):
    pass


class VolumeService(service.Service):
    """
    There is one VolumeNode running on each host.
    However, each VolumeNode can report on the state of
    *all* volumes in the cluster.
    """
    def __init__(self):
        super(VolumeService, self).__init__()
        self._exec_init_volumes()

    @defer.inlineCallbacks
    @validate.rangetest(size=(0, 1000))
    def create_volume(self, size, user_id, project_id):
        """
        Creates an exported volume (fake or real),
        restarts exports to make it available.
        Volume at this point has size, owner, and zone.
        """
        logging.debug("Creating volume of size: %s" % (size))

        vol = models.Volume()
        vol.volume_id = utils.generate_uid('vol')
        vol.node_name = FLAGS.node_name
        vol.size = size
        vol.user_id = user_id
        vol.project_id = project_id
        vol.availability_zone = FLAGS.storage_availability_zone
        vol.status = "creating" # creating | available | in-use
        vol.attach_status = "detached"  # attaching | attached | detaching | detached
        vol.save()
        yield self._exec_create_volume(vol)
        yield self._setup_export(vol)
        # TODO(joshua): We need to trigger a fanout message
        #               for aoe-discover on all the nodes
        vol.status = "available"
        vol.save()
        logging.debug("restarting exports")
        yield self._exec_ensure_exports()
        defer.returnValue(vol.id)

    @defer.inlineCallbacks
    def delete_volume(self, volume_id):
        logging.debug("Deleting volume with id of: %s" % (volume_id))
        vol = models.Volume.find(volume_id)
        if vol.attach_status == "attached":
            raise exception.Error("Volume is still attached")
        if vol.node_name != FLAGS.node_name:
            raise exception.Error("Volume is not local to this node")
        yield self._exec_delete_volume(vol)
        yield vol.delete()
        defer.returnValue(True)

    @defer.inlineCallbacks
    def _exec_create_volume(self, vol):
        if FLAGS.fake_storage:
            defer.returnValue(None)
        if str(vol.size) == '0':
            sizestr = '100M'
        else:
            sizestr = '%sG' % vol.size
        yield process.simple_execute(
                "sudo lvcreate -L %s -n %s %s" % (sizestr,
                                                  vol.volume_id,
                                                  FLAGS.volume_group),
                error_ok=1)

    @defer.inlineCallbacks
    def _exec_delete_volume(self, vol):
        if FLAGS.fake_storage:
            defer.returnValue(None)
        yield process.simple_execute(
                "sudo lvremove -f %s/%s" % (FLAGS.volume_group,
                                            vol.volume_id), error_ok=1)

    @defer.inlineCallbacks
    def _setup_export(self, vol):
        # FIXME: abstract this. also remove vol.export_device.xxx cheat
        session = models.NovaBase.get_session()
        query = session.query(models.ExportDevice).filter_by(volume=None)
        export_device = query.with_lockmode("update").first()
        # NOTE(vish): if with_lockmode isn't supported, as in sqlite,
        #             then this has concurrency issues
        if not export_device:
            raise NoMoreBlades()
        export_device.volume_id = vol.id
        session.add(export_device)
        session.commit()
        # FIXME: aoe_device is redundant, should be turned into a method
        vol.aoe_device = "e%s.%s" % (export_device.shelf_id,
                                     export_device.blade_id)
        vol.save()
        yield self._exec_setup_export(vol)

    @defer.inlineCallbacks
    def _exec_setup_export(self, vol):
        if FLAGS.fake_storage:
            defer.returnValue(None)
        yield process.simple_execute(
                "sudo vblade-persist setup %s %s %s /dev/%s/%s" %
                (self, vol.export_device.shelf_id,
                 vol.export_device.blade_id,
                 FLAGS.aoe_eth_dev,
                 FLAGS.volume_group,
                 vol.volume_id), error_ok=1)

    @defer.inlineCallbacks
    def _remove_export(self, vol):
        if not vol.export_device:
            defer.returnValue(False)
        yield self._exec_remove_export(vol)
        defer.returnValue(True)

    @defer.inlineCallbacks
    def _exec_remove_export(self, vol):
        if FLAGS.fake_storage:
            defer.returnValue(None)
        yield process.simple_execute(
                "sudo vblade-persist stop %s %s" % (self, vol.export_device.shelf_id,
                                                    vol.export_device.blade_id), error_ok=1)
        yield process.simple_execute(
                "sudo vblade-persist destroy %s %s" % (self, vol.export_device.shelf_id,
                                                       vol.export_device.blade_id), error_ok=1)
    @defer.inlineCallbacks
    def _exec_ensure_exports(self):
        if FLAGS.fake_storage:
            defer.returnValue(None)
        # NOTE(vish): these commands sometimes sends output to stderr for warnings
        yield process.simple_execute("sudo vblade-persist auto all", error_ok=1)
        yield process.simple_execute("sudo vblade-persist start all", error_ok=1)

    @defer.inlineCallbacks
    def _exec_init_volumes(self):
        if FLAGS.fake_storage:
            defer.returnValue(None)
        yield process.simple_execute(
                "sudo pvcreate %s" % (FLAGS.storage_dev))
        yield process.simple_execute(
                "sudo vgcreate %s %s" % (FLAGS.volume_group,
                                         FLAGS.storage_dev))

    def start_attach(self, volume_id, instance_id, mountpoint):
        vol = models.Volume.find(volume_id)
        vol.instance_id = instance_id
        vol.mountpoint = mountpoint
        vol.status = "in-use"
        vol.attach_status = "attaching"
        vol.attach_time = utils.isotime()
        vol.save()

    def finish_attach(self, volume_id):
        vol = models.Volume.find(volume_id)
        vol.attach_status = "attached"
        vol.save()

    def start_detach(self, volume_id):
        vol = models.Volume.find(volume_id)
        vol.attach_status = "detaching"
        vol.save()

    def finish_detach(self, volume_id):
        vol = models.Volume.find(volume_id)
        vol.instance_id = None
        vol.mountpoint = None
        vol.status = "available"
        vol.attach_status = "detached"
        vol.save()
