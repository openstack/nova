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

from nova import db
from nova import exception
from nova import flags
from nova import process
from nova import service
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
    def create_volume(self, size, user_id, project_id, context=None):
        """
        Creates an exported volume (fake or real),
        restarts exports to make it available.
        Volume at this point has size, owner, and zone.
        """
        logging.debug("Creating volume of size: %s" % (size))

        vol = {}
        vol['node_name'] = FLAGS.node_name
        vol['size'] = size
        vol['user_id'] = user_id
        vol['project_id'] = project_id
        vol['availability_zone'] = FLAGS.storage_availability_zone
        vol['status'] = "creating" # creating | available | in-use
        # attaching | attached | detaching | detached
        vol['attach_status'] = "detached"
        volume_id = db.volume_create(context, vol)
        yield self._exec_create_volume(volume_id, size)
        (shelf_id, blade_id) = db.volume_allocate_shelf_and_blade(context,
                                                                  volume_id)
        yield self._exec_create_export(volume_id, shelf_id, blade_id)
        # TODO(joshua): We need to trigger a fanout message
        #               for aoe-discover on all the nodes
        yield self._exec_ensure_exports()
        db.volume_update(context, volume_id, {'status': 'available'})
        logging.debug("restarting exports")
        defer.returnValue(volume_id)

    @defer.inlineCallbacks
    def delete_volume(self, volume_id, context=None):
        logging.debug("Deleting volume with id of: %s" % (volume_id))
        volume_ref = db.volume_get(context, volume_id)
        if volume_ref['attach_status'] == "attached":
            raise exception.Error("Volume is still attached")
        if volume_ref['node_name'] != FLAGS.node_name:
            raise exception.Error("Volume is not local to this node")
        shelf_id, blade_id = db.volume_get_shelf_and_blade(context,
                                                           volume_id)
        yield self._exec_remove_export(volume_id, shelf_id, blade_id)
        yield self._exec_delete_volume(volume_id)
        db.volume_destroy(context, volume_id)
        defer.returnValue(True)

    @defer.inlineCallbacks
    def _exec_create_volume(self, volume_id, size):
        if FLAGS.fake_storage:
            defer.returnValue(None)
        if int(size) == 0:
            sizestr = '100M'
        else:
            sizestr = '%sG' % size
        yield process.simple_execute(
                "sudo lvcreate -L %s -n %s %s" % (sizestr,
                                                  volume_id,
                                                  FLAGS.volume_group),
                terminate_on_stderr=False)

    @defer.inlineCallbacks
    def _exec_delete_volume(self, volume_id):
        if FLAGS.fake_storage:
            defer.returnValue(None)
        yield process.simple_execute(
                "sudo lvremove -f %s/%s" % (FLAGS.volume_group,
                                            volume_id),
                terminate_on_stderr=False)

    @defer.inlineCallbacks
    def _exec_create_export(self, volume_id, shelf_id, blade_id):
        if FLAGS.fake_storage:
            defer.returnValue(None)
        yield process.simple_execute(
                "sudo vblade-persist setup %s %s %s /dev/%s/%s" %
                (self,
                 shelf_id,
                 blade_id,
                 FLAGS.aoe_eth_dev,
                 FLAGS.volume_group,
                 volume_id),
                terminate_on_stderr=False)

    @defer.inlineCallbacks
    def _exec_remove_export(self, _volume_id, shelf_id, blade_id):
        if FLAGS.fake_storage:
            defer.returnValue(None)
        yield process.simple_execute(
                "sudo vblade-persist stop %s %s" % (self, shelf_id,
                                                    blade_id),
                terminate_on_stderr=False)
        yield process.simple_execute(
                "sudo vblade-persist destroy %s %s" % (self, shelf_id,
                                                       blade_id),
                terminate_on_stderr=False)

    @defer.inlineCallbacks
    def _exec_ensure_exports(self):
        if FLAGS.fake_storage:
            defer.returnValue(None)
        # NOTE(vish): these commands sometimes sends output to stderr for warnings
        yield process.simple_execute("sudo vblade-persist auto all",
                                     terminate_on_stderr=False)
        yield process.simple_execute("sudo vblade-persist start all",
                                     terminate_on_stderr=False)

    @defer.inlineCallbacks
    def _exec_init_volumes(self):
        if FLAGS.fake_storage:
            defer.returnValue(None)
        yield process.simple_execute(
                "sudo pvcreate %s" % (FLAGS.storage_dev))
        yield process.simple_execute(
                "sudo vgcreate %s %s" % (FLAGS.volume_group,
                                         FLAGS.storage_dev))
