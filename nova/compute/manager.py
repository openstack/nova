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
Handles all code relating to instances (guest vms)
"""

import base64
import logging
import os

from twisted.internet import defer

from nova import db
from nova import exception
from nova import flags
from nova import process
from nova import manager
from nova import utils
from nova.compute import power_state


FLAGS = flags.FLAGS
flags.DEFINE_string('instances_path', utils.abspath('../instances'),
                    'where instances are stored on disk')
flags.DEFINE_string('compute_driver', 'nova.virt.connection.get_connection',
                    'Driver to use for volume creation')


class ComputeManager(manager.Manager):
    """
    Manages the running instances.
    """
    def __init__(self, compute_driver=None, *args, **kwargs):
        """Load configuration options and connect to the hypervisor."""
        # TODO(vish): sync driver creation logic with the rest of the system
        if not compute_driver:
            compute_driver = FLAGS.compute_driver
        self.driver = utils.import_object(compute_driver)
        self.network_manager = utils.import_object(FLAGS.network_manager)
        super(ComputeManager, self).__init__(*args, **kwargs)

    def _update_state(self, context, instance_id):
        """Update the state of an instance from the driver info"""
        # FIXME(ja): include other fields from state?
        instance_ref = db.instance_get(context, instance_id)
        state = self.driver.get_info(instance_ref.name)['state']
        db.instance_state(context, instance_id, state)

    @defer.inlineCallbacks
    @exception.wrap_exception
    def run_instance(self, context, instance_id, **_kwargs):
        """Launch a new instance with specified options."""
        instance_ref = db.instance_get(context, instance_id)
        if instance_ref['str_id'] in self.driver.list_instances():
            raise exception.Error("Instance has already been created")
        logging.debug("Starting instance %s...", instance_id)
        project_id = instance_ref['project_id']
        self.network_manager.setup_compute_network(context, project_id)
        db.instance_update(context,
                           instance_id,
                           {'host': FLAGS.host})

        # TODO(vish) check to make sure the availability zone matches
        db.instance_state(context,
                          instance_id,
                          power_state.NOSTATE,
                          'spawning')

        try:
            yield self.driver.spawn(instance_ref)
        except:  # pylint: disable-msg=W0702
            logging.exception("Failed to spawn instance %s",
                              instance_ref['name'])
            db.instance_state(context, instance_id, power_state.SHUTDOWN)

        self._update_state(context, instance_id)

    @defer.inlineCallbacks
    @exception.wrap_exception
    def terminate_instance(self, context, instance_id):
        """Terminate an instance on this machine."""
        logging.debug("Got told to terminate instance %s", instance_id)
        instance_ref = db.instance_get(context, instance_id)

        # TODO(vish): move this logic to layer?
        if instance_ref['state'] == power_state.SHUTOFF:
            db.instance_destroy(context, instance_id)
            raise exception.Error('trying to destroy already destroyed'
                                  ' instance: %s' % instance_id)

        db.instance_state(context,
                          instance_id,
                          power_state.NOSTATE,
                          'shutting_down')
        yield self.driver.destroy(instance_ref)

        # TODO(ja): should we keep it in a terminated state for a bit?
        db.instance_destroy(context, instance_id)

    @defer.inlineCallbacks
    @exception.wrap_exception
    def reboot_instance(self, context, instance_id):
        """Reboot an instance on this server."""
        self._update_state(context, instance_id)
        instance_ref = db.instance_get(context, instance_id)

        if instance_ref['state'] != power_state.RUNNING:
            raise exception.Error(
                    'trying to reboot a non-running'
                    'instance: %s (state: %s excepted: %s)' %
                    (instance_ref['str_id'],
                     instance_ref['state'],
                     power_state.RUNNING))

        logging.debug('rebooting instance %s', instance_ref['name'])
        db.instance_state(context,
                          instance_id,
                          power_state.NOSTATE,
                          'rebooting')
        yield self.driver.reboot(instance_ref)
        self._update_state(context, instance_id)

    @exception.wrap_exception
    def get_console_output(self, context, instance_id):
        """Send the console output for an instance."""
        # TODO(vish): Move this into the driver layer

        logging.debug("Getting console output for %s", (instance_id))
        instance_ref = db.instance_get(context, instance_id)

        if FLAGS.connection_type == 'libvirt':
            fname = os.path.abspath(os.path.join(FLAGS.instances_path,
                                                 instance_ref['str_id'],
                                                 'console.log'))
            with open(fname, 'r') as f:
                output = f.read()
        else:
            output = 'FAKE CONSOLE OUTPUT'

        # TODO(termie): this stuff belongs in the API layer, no need to
        #               munge the data we send to ourselves
        output = {"InstanceId": instance_id,
                  "Timestamp": "2",
                  "output": base64.b64encode(output)}
        return output

    @defer.inlineCallbacks
    @exception.wrap_exception
    def attach_volume(self, context, instance_id, volume_id, mountpoint):
        """Attach a volume to an instance."""
        # TODO(termie): check that instance_id exists
        volume_ref = db.volume_get(context, volume_id)
        yield self._init_aoe()
        # TODO(vish): Move this into the driver layer
        yield process.simple_execute(
                "sudo virsh attach-disk %s /dev/etherd/%s %s" %
                (instance_id,
                 volume_ref['aoe_device'],
                 mountpoint.rpartition('/dev/')[2]))
        db.volume_attached(context, volume_id, instance_id, mountpoint)
        defer.returnValue(True)

    @defer.inlineCallbacks
    @exception.wrap_exception
    def detach_volume(self, context, instance_id, volume_id):
        """Detach a volume from an instance."""
        # despite the documentation, virsh detach-disk just wants the device
        # name without the leading /dev/
        # TODO(termie): check that instance_id exists
        volume_ref = db.volume_get(context, volume_id)
        target = volume_ref['mountpoint'].rpartition('/dev/')[2]
        # TODO(vish): Move this into the driver layer
        yield process.simple_execute(
                "sudo virsh detach-disk %s %s " % (instance_id, target))
        db.volume_detached(context, volume_id)
        defer.returnValue(True)

    @defer.inlineCallbacks
    def _init_aoe(self):
        """Discover aoe exported devices"""
        # TODO(vish): these shell calls should move into volume manager.
        yield process.simple_execute("sudo aoe-discover")
        yield process.simple_execute("sudo aoe-stat")
