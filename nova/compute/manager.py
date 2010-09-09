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
import datetime
import logging
import os

from twisted.internet import defer

from nova import exception
from nova import flags
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
        self.volume_manager = utils.import_object(FLAGS.volume_manager)
        super(ComputeManager, self).__init__(*args, **kwargs)

    def _update_state(self, context, instance_id):
        """Update the state of an instance from the driver info"""
        # FIXME(ja): include other fields from state?
        instance_ref = self.db.instance_get(context, instance_id)
        state = self.driver.get_info(instance_ref.name)['state']
        self.db.instance_set_state(context, instance_id, state)

    @defer.inlineCallbacks
    @exception.wrap_exception
    def run_instance(self, context, instance_id, **_kwargs):
        """Launch a new instance with specified options."""
        instance_ref = self.db.instance_get(context, instance_id)
        if instance_ref['str_id'] in self.driver.list_instances():
            raise exception.Error("Instance has already been created")
        logging.debug("instance %s: starting...", instance_id)
        project_id = instance_ref['project_id']
        self.network_manager.setup_compute_network(context, project_id)
        self.db.instance_update(context,
                                instance_id,
                                {'host': self.host})

        # TODO(vish) check to make sure the availability zone matches
        self.db.instance_set_state(context,
                                   instance_id,
                                   power_state.NOSTATE,
                                   'spawning')

        try:
            yield self.driver.spawn(instance_ref)
            now = datetime.datetime.now()
            self.db.instance_update(None, instance_id, {'launched_at': now})
        except Exception:  # pylint: disable-msg=W0702
            logging.exception("instance %s: Failed to spawn",
                              instance_ref['name'])
            self.db.instance_set_state(context,
                                       instance_id,
                                       power_state.SHUTDOWN)

        self._update_state(context, instance_id)

    @defer.inlineCallbacks
    @exception.wrap_exception
    def terminate_instance(self, context, instance_id):
        """Terminate an instance on this machine."""
        logging.debug("instance %s: terminating", instance_id)
        instance_ref = self.db.instance_get(context, instance_id)

        if instance_ref['state'] == power_state.SHUTOFF:
            self.db.instance_destroy(context, instance_id)
            raise exception.Error('trying to destroy already destroyed'
                                  ' instance: %s' % instance_id)

        self.db.instance_set_state(context,
                                   instance_id,
                                   power_state.NOSTATE,
                                   'shutting_down')
        yield self.driver.destroy(instance_ref)
        now = datetime.datetime.now()
        self.db.instance_update(None, instance_id, {'terminated_at': now})

        # TODO(ja): should we keep it in a terminated state for a bit?
        self.db.instance_destroy(context, instance_id)

    @defer.inlineCallbacks
    @exception.wrap_exception
    def reboot_instance(self, context, instance_id):
        """Reboot an instance on this server."""
        self._update_state(context, instance_id)
        instance_ref = self.db.instance_get(context, instance_id)

        if instance_ref['state'] != power_state.RUNNING:
            raise exception.Error(
                    'trying to reboot a non-running'
                    'instance: %s (state: %s excepted: %s)' %
                    (instance_ref['str_id'],
                     instance_ref['state'],
                     power_state.RUNNING))

        logging.debug('instance %s: rebooting', instance_ref['name'])
        self.db.instance_set_state(context,
                                   instance_id,
                                   power_state.NOSTATE,
                                   'rebooting')
        yield self.driver.reboot(instance_ref)
        self._update_state(context, instance_id)

    @exception.wrap_exception
    def get_console_output(self, context, instance_id):
        """Send the console output for an instance."""
        # TODO(vish): Move this into the driver layer

        logging.debug("instance %s: getting console output", instance_id)
        instance_ref = self.db.instance_get(context, instance_id)

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
        logging.debug("instance %s: attaching volume %s to %s", instance_id,
            volume_id, mountpoint)
        instance_ref = self.db.instance_get(context, instance_id)
        dev_path = yield self.volume_manager.setup_compute_volume(context,
                                                                  volume_id)
        yield self.driver.attach_volume(instance_ref['str_id'],
                                        dev_path,
                                        mountpoint)
        self.db.volume_attached(context, volume_id, instance_id, mountpoint)
        defer.returnValue(True)

    @defer.inlineCallbacks
    @exception.wrap_exception
    def detach_volume(self, context, instance_id, volume_id):
        """Detach a volume from an instance."""
        logging.debug("instance %s: detaching volume %s",
                      instance_id,
                      volume_id)
        instance_ref = self.db.instance_get(context, instance_id)
        volume_ref = self.db.volume_get(context, volume_id)
        self.driver.detach_volume(instance_ref['str_id'],
                                  volume_ref['mountpoint'])
        self.db.volume_detached(context, volume_id)
        defer.returnValue(True)
