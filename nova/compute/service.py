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
        """ load configuration options for this node and connect to the hypervisor"""
        super(ComputeService, self).__init__()
        self._instances = {}
        self._conn = virt_connection.get_connection()
        # TODO(joshua): This needs to ensure system state, specifically: modprobe aoe

    def noop(self):
        """ simple test of an AMQP message call """
        return defer.succeed('PONG')

    def update_state(self, instance_id):
        inst = models.Instance.find(instance_id)
        # FIXME(ja): include other fields from state?
        inst.state = self._conn.get_info(inst.name)['state']
        inst.save()

    @exception.wrap_exception
    def adopt_instances(self):
        """ if there are instances already running, adopt them """
        return defer.succeed(0)
        instance_names = self._conn.list_instances()
        for name in instance_names:
            try:
                new_inst = Instance.fromName(self._conn, name)
                new_inst.update_state()
            except:
                pass
        return defer.succeed(len(self._instances))

    @defer.inlineCallbacks
    def report_state(self, nodename, daemon):
        # TODO(termie): make this pattern be more elegant. -todd
        try:
            record = model.Daemon(nodename, daemon)
            record.heartbeat()
            if getattr(self, "model_disconnected", False):
                self.model_disconnected = False
                logging.error("Recovered model server connection!")

        except model.ConnectionError, ex:
            if not getattr(self, "model_disconnected", False):
                self.model_disconnected = True
                logging.exception("model server went away")
        yield

    @defer.inlineCallbacks
    @exception.wrap_exception
    def run_instance(self, instance_id, **_kwargs):
        """ launch a new instance with specified options """
        inst = models.Instance.find(instance_id)
        if inst.name in self._conn.list_instances():
            raise exception.Error("Instance has already been created")
        logging.debug("Starting instance %s..." % (instance_id))
        inst = models.Instance.find(instance_id)
        # NOTE(vish): passing network type allows us to express the
        #             network without making a call to network to find
        #             out which type of network to setup
        network_service.setup_compute_network(inst.project_id)
        inst.node_name = FLAGS.node_name
        inst.save()

        # TODO(vish) check to make sure the availability zone matches
        inst.set_state(power_state.NOSTATE, 'spawning')

        try:
            yield self._conn.spawn(inst)
        except:
            logging.exception("Failed to spawn instance %s" % inst.name)
            inst.set_state(power_state.SHUTDOWN)

        self.update_state(instance_id)

    @defer.inlineCallbacks
    @exception.wrap_exception
    def terminate_instance(self, instance_id):
        """ terminate an instance on this machine """
        logging.debug("Got told to terminate instance %s" % instance_id)
        inst = models.Instance.find(instance_id)

        if inst.state == power_state.SHUTOFF:
            # self.datamodel.destroy() FIXME: RE-ADD ?????
            raise exception.Error('trying to destroy already destroyed'
                                  ' instance: %s' % instance_id)

        inst.set_state(power_state.NOSTATE, 'shutting_down')
        yield self._conn.destroy(inst)
        # FIXME(ja): should we keep it in a terminated state for a bit?
        inst.delete()

    @defer.inlineCallbacks
    @exception.wrap_exception
    def reboot_instance(self, instance_id):
        """ reboot an instance on this server
        KVM doesn't support reboot, so we terminate and restart """
        self.update_state(instance_id)
        instance = models.Instance.find(instance_id)

        # FIXME(ja): this is only checking the model state - not state on disk?
        if instance.state != power_state.RUNNING:
            raise exception.Error(
                    'trying to reboot a non-running'
                    'instance: %s (state: %s excepted: %s)' % (instance.name, instance.state, power_state.RUNNING))

        logging.debug('rebooting instance %s' % instance.name)
        instance.set_state(power_state.NOSTATE, 'rebooting')
        yield self._conn.reboot(instance)
        self.update_state(instance_id)

    @exception.wrap_exception
    def get_console_output(self, instance_id):
        """ send the console output for an instance """
        # FIXME: Abstract this for Xen

        logging.debug("Getting console output for %s" % (instance_id))
        inst = models.Instance.find(instance_id)

        if FLAGS.connection_type == 'libvirt':
            fname = os.path.abspath(
                    os.path.join(FLAGS.instances_path, inst.name, 'console.log'))
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
    def attach_volume(self, instance_id = None,
                      volume_id = None, mountpoint = None):
        volume = volume_service.get_volume(volume_id)
        yield self._init_aoe()
        yield process.simple_execute(
                "sudo virsh attach-disk %s /dev/etherd/%s %s" %
                (instance_id,
                 volume['aoe_device'],
                 mountpoint.rpartition('/dev/')[2]))
        volume.finish_attach()
        defer.returnValue(True)

    @defer.inlineCallbacks
    def _init_aoe(self):
        yield process.simple_execute("sudo aoe-discover")
        yield process.simple_execute("sudo aoe-stat")

    @defer.inlineCallbacks
    @exception.wrap_exception
    def detach_volume(self, instance_id, volume_id):
        """ detach a volume from an instance """
        # despite the documentation, virsh detach-disk just wants the device
        # name without the leading /dev/
        volume = volume_service.get_volume(volume_id)
        target = volume['mountpoint'].rpartition('/dev/')[2]
        yield process.simple_execute(
                "sudo virsh detach-disk %s %s " % (instance_id, target))
        volume.finish_detach()
        defer.returnValue(True)


class Group(object):
    def __init__(self, group_id):
        self.group_id = group_id


class ProductCode(object):
    def __init__(self, product_code):
        self.product_code = product_code
