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
Volume manager manages creating, attaching, detaching, and
destroying persistent storage volumes, ala EBS.
"""

import logging

from twisted.internet import defer

from nova import exception
from nova import flags
from nova import manager
from nova import utils


FLAGS = flags.FLAGS
flags.DEFINE_string('storage_availability_zone',
                    'nova',
                    'availability zone of this service')
flags.DEFINE_boolean('fake_storage', False,
                     'Should we make real storage volumes to attach?')
flags.DEFINE_string('volume_driver', 'nova.volume.driver.AOEDriver',
                    'Driver to use for volume creation')
flags.DEFINE_integer('num_shelves',
                    100,
                    'Number of vblade shelves')
flags.DEFINE_integer('blades_per_shelf',
                    16,
                    'Number of vblade blades per shelf')


class AOEManager(manager.Manager):
    """Manages Ata-Over_Ethernet volumes"""
    def __init__(self, volume_driver=None, *args, **kwargs):
        if not volume_driver:
            # NOTE(vish): support the legacy fake storage flag
            if FLAGS.fake_storage:
                volume_driver = 'nova.volume.driver.FakeAOEDriver'
            else:
                volume_driver = FLAGS.volume_driver
        self.driver = utils.import_object(volume_driver)
        super(AOEManager, self).__init__(*args, **kwargs)

    def _ensure_blades(self, context):
        """Ensure that blades have been created in datastore"""
        total_blades = FLAGS.num_shelves * FLAGS.blades_per_shelf
        if self.db.export_device_count(context) >= total_blades:
            return
        for shelf_id in xrange(FLAGS.num_shelves):
            for blade_id in xrange(FLAGS.blades_per_shelf):
                dev = {'shelf_id': shelf_id, 'blade_id': blade_id}
                self.db.export_device_create(context, dev)

    @defer.inlineCallbacks
    def create_volume(self, context, volume_id):
        """Creates and exports the volume"""
        logging.info("volume %s: creating", volume_id)

        volume_ref = self.db.volume_get(context, volume_id)

        self.db.volume_update(context,
                              volume_id,
                              {'node_name': FLAGS.node_name})

        size = volume_ref['size']
        logging.debug("volume %s: creating lv of size %sG", volume_id, size)
        yield self.driver.create_volume(volume_id, size)

        logging.debug("volume %s: allocating shelf & blade", volume_id)
        self._ensure_blades(context)
        rval = self.db.volume_allocate_shelf_and_blade(context, volume_id)
        (shelf_id, blade_id) = rval

        logging.debug("volume %s: exporting shelf %s & blade %s", (volume_id,
                 shelf_id, blade_id))

        yield self.driver.create_export(volume_id, shelf_id, blade_id)
        # TODO(joshua): We need to trigger a fanout message
        #               for aoe-discover on all the nodes

        self.db.volume_update(context, volume_id, {'status': 'available'})

        logging.debug("volume %s: re-exporting all values", volume_id)
        yield self.driver.ensure_exports()

        logging.debug("volume %s: created successfully", volume_id)
        defer.returnValue(volume_id)

    @defer.inlineCallbacks
    def delete_volume(self, context, volume_id):
        """Deletes and unexports volume"""
        logging.debug("Deleting volume with id of: %s", volume_id)
        volume_ref = self.db.volume_get(context, volume_id)
        if volume_ref['attach_status'] == "attached":
            raise exception.Error("Volume is still attached")
        if volume_ref['node_name'] != FLAGS.node_name:
            raise exception.Error("Volume is not local to this node")
        shelf_id, blade_id = self.db.volume_get_shelf_and_blade(context,
                                                           volume_id)
        yield self.driver.remove_export(volume_id, shelf_id, blade_id)
        yield self.driver.delete_volumevolume_id
        self.db.volume_destroy(context, volume_id)
        defer.returnValue(True)
