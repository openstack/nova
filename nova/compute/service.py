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
Compute Service:

    Runs on each compute host, managing the
    hypervisor using the virt module.

"""

import base64
import logging
import os

from twisted.internet import defer

from nova import db
from nova import exception
from nova import flags
from nova import process
from nova import service
from nova import utils
from nova import models
from nova.compute import power_state
from nova.network import service as network_service
from nova.virt import connection as virt_connection
from nova.volume import service as volume_service


FLAGS = flags.FLAGS
flags.DEFINE_string('instances_path', utils.abspath('../instances'),
                    'where instances are stored on disk')


class ComputeService(service.Service):
    """
    Manages the running instances.
    """
    def __init__(self):
        """Load configuration options and connect to the hypervisor."""
        super(ComputeService, self).__init__()
        self._instances = {}
        self._conn = virt_connection.get_connection()
        # TODO(joshua): This needs to ensure system state, specifically
        #               modprobe aoe

    def noop(self):
        """Simple test of an AMQP message call."""
        return defer.succeed('PONG')

    def update_state(self, instance_id, context):
        # FIXME(ja): include other fields from state?
        instance_ref = db.instance_get(context, instance_id)
        state = self._conn.get_info(instance_ref.name)['state']
        db.instance_state(context, instance_id, state)

    @defer.inlineCallbacks
    @exception.wrap_exception
    def run_instance(self, instance_id, context=None, **_kwargs):
        """Launch a new instance with specified options."""
        instance_ref = db.instance_get(context, instance_id)
        if instance_ref['name'] in self._conn.list_instances():
            raise exception.Error("Instance has already been created")
        logging.debug("Starting instance %s..." % (instance_id))

        # NOTE(vish): passing network type allows us to express the
        #             network without making a call to network to find
        #             out which type of network to setup
        network_service.setup_compute_network(instance_ref['project_id'])
        db.instance_update(context, instance_id, {'node_name': FLAGS.node_name})

        # TODO(vish) check to make sure the availability zone matches
        db.instance_state(context, instance_id, power_state.NOSTATE, 'spawning')

        try:
            yield self._conn.spawn(instance_ref)
        except:
            logging.exception("Failed to spawn instance %s" %
                              instance_ref['name'])
            db.instance_state(context, instance_id, power_state.SHUTDOWN)

        self.update_state(instance_id, context)

    @defer.inlineCallbacks
    @exception.wrap_exception
    def terminate_instance(self, instance_id, context=None):
        """Terminate an instance on this machine."""
        logging.debug("Got told to terminate instance %s" % instance_id)
        instance_ref = db.instance_get(context, instance_id)

        if instance_ref['state'] == power_state.SHUTOFF:
            # self.datamodel.destroy() FIXME: RE-ADD?
            raise exception.Error('trying to destroy already destroyed'
                                  ' instance: %s' % instance_id)

        db.instance_state(
                context, instance_id, power_state.NOSTATE, 'shutting_down')
        yield self._conn.destroy(instance_ref)

        # FIXME(ja): should we keep it in a terminated state for a bit?
        db.instance_destroy(context, instance_id)

    @defer.inlineCallbacks
    @exception.wrap_exception
    def reboot_instance(self, instance_id, context=None):
        """Reboot an instance on this server.

        KVM doesn't support reboot, so we terminate and restart.
        
        """
        self.update_state(instance_id, context)
        instance_ref = db.instance_get(context, instance_id)

        # FIXME(ja): this is only checking the model state - not state on disk?
        if instance_ref['state'] != power_state.RUNNING:
            raise exception.Error(
                    'trying to reboot a non-running'
                    'instance: %s (state: %s excepted: %s)' %
                    (instance_ref['name'],
                     instance_ref['state'],
                     power_state.RUNNING))

        logging.debug('rebooting instance %s' % instance_ref['name'])
        db.instance_state(
                context, instance_id, power_state.NOSTATE, 'rebooting')
        yield self._conn.reboot(instance_ref)
        self.update_state(instance_id, context)

    @exception.wrap_exception
    def get_console_output(self, instance_id, context=None):
        """Send the console output for an instance."""
        # FIXME: Abstract this for Xen

        logging.debug("Getting console output for %s" % (instance_id))
        instance_ref = db.instance_get(context, instance_id)

        if FLAGS.connection_type == 'libvirt':
            fname = os.path.abspath(os.path.join(FLAGS.instances_path,
                                                 instance_ref['name'],
                                                 'console.log'))
            with open(fname, 'r') as f:
                output = f.read()
        else:
            output = 'FAKE CONSOLE OUTPUT'

        # TODO(termie): this stuff belongs in the API layer, no need to
        #               munge the data we send to ourselves
        output = {"InstanceId" : instance_id,
                  "Timestamp" : "2",
                  "output" : base64.b64encode(output)}
        return output

    @defer.inlineCallbacks
    @exception.wrap_exception
    def attach_volume(self, instance_id=None, volume_id=None, mountpoint=None,
                      context=None):
        """Attach a volume to an instance."""
        # TODO(termie): check that instance_id exists
        volume_ref = volume_get(context, volume_id)
        yield self._init_aoe()
        yield process.simple_execute(
                "sudo virsh attach-disk %s /dev/etherd/%s %s" %
                (instance_id,
                 volume['aoe_device'],
                 mountpoint.rpartition('/dev/')[2]))
        volume_attached(context, volume_id)
        defer.returnValue(True)

    @defer.inlineCallbacks
    @exception.wrap_exception
    def detach_volume(self, instance_id, volume_id, context=None):
        """Detach a volume from an instance."""
        # despite the documentation, virsh detach-disk just wants the device
        # name without the leading /dev/
        # TODO(termie): check that instance_id exists
        volume_ref = volume_get(context, volume_id)
        target = volume['mountpoint'].rpartition('/dev/')[2]
        yield process.simple_execute(
                "sudo virsh detach-disk %s %s " % (instance_id, target))
        volume_detached(context, volume_id)
        defer.returnValue(True)

    @defer.inlineCallbacks
    def _init_aoe(self):
        yield process.simple_execute("sudo aoe-discover")
        yield process.simple_execute("sudo aoe-stat")
