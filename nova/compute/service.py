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
import json
import logging
import os
import sys
from twisted.internet import defer
from twisted.internet import task

from nova import exception
from nova import flags
from nova import process
from nova import service
from nova import utils
from nova.compute import disk
from nova import models
from nova.compute import power_state
from nova.compute.instance_types import INSTANCE_TYPES
from nova.network import service as network_service
from nova.objectstore import image # for image_path flag
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

    def get_instance(self, instance_id):
        session = models.create_session()
        return session.query(models.Instance).filter_by(id=instance_id).one()

    def update_state(self, instance_id):
        session = models.create_session()
        inst = session.query(models.Instance).filter_by(id=instance_id).one()
        # FIXME(ja): include other fields from state?
        inst.state = self._conn.get_info(instance_id)['state'] 
        session.flush()

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
        logging.debug("Starting instance %s..." % (instance_id))
        session = models.create_session()
        inst = session.query(models.Instance).filter_by(id=instance_id).first()
        # NOTE(vish): passing network type allows us to express the
        #             network without making a call to network to find
        #             out which type of network to setup
        network_service.setup_compute_network(inst)
        inst.node_name = FLAGS.node_name
        session.commit()

        # TODO(vish) check to make sure the availability zone matches
        inst.set_state(power_state.NOSTATE, 'spawning')
        session.commit()

        try:
            yield self._conn.spawn(inst)
        except Exception, ex:
            logging.debug(ex)
            inst.set_state(power_state.SHUTDOWN)

        self.update_state(instance_id)

    @defer.inlineCallbacks
    @exception.wrap_exception
    def terminate_instance(self, instance_id):
        """ terminate an instance on this machine """
        logging.debug("Got told to terminate instance %s" % instance_id)
        session = models.create_session()
        instance = session.query(models.Instance).filter_by(id=instance_id).one()

        if instance.state == power_state.SHUTOFF:
            # self.datamodel.destroy() FIXME: RE-ADD ?????
            raise exception.Error('trying to destroy already destroyed'
                                  ' instance: %s' % instance_id)

        instance.set_state(power_state.NOSTATE, 'shutting_down')
        yield self._conn.destroy(instance)
        # FIXME(ja): should we keep it in a terminated state for a bit?
        session.delete(instance)
        session.flush()

    @defer.inlineCallbacks
    @exception.wrap_exception
    def reboot_instance(self, instance_id):
        """ reboot an instance on this server
        KVM doesn't support reboot, so we terminate and restart """
        self.update_state(instance_id)
        instance = self.get_instance(instance_id)

        # FIXME(ja): this is only checking the model state - not state on disk?
        if instance.state != power_state.RUNNING:
            raise exception.Error(
                    'trying to reboot a non-running'
                    'instance: %s (state: %s excepted: %s)' % (instance.id, instance.state, power_state.RUNNING))

        logging.debug('rebooting instance %s' % instance.id)
        instance.set_state(power_state.NOSTATE, 'rebooting')
        yield self._conn.reboot(instance)
        self.update_state(instance_id)

    @exception.wrap_exception
    def get_console_output(self, instance_id):
        """ send the console output for an instance """
        # FIXME: Abstract this for Xen

        logging.debug("Getting console output for %s" % (instance_id))
        session = models.create_session()
        inst = self.get_instance(instance_id)

        if FLAGS.connection_type == 'libvirt':
            fname = os.path.abspath(
                    os.path.join(FLAGS.instances_path, inst.id, 'console.log'))
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


class Instance(object):

    NOSTATE = 0x00
    RUNNING = 0x01
    BLOCKED = 0x02
    PAUSED = 0x03
    SHUTDOWN = 0x04
    SHUTOFF = 0x05
    CRASHED = 0x06

    def __init__(self, conn, name, data):
        """ spawn an instance with a given name """
        self._conn = conn
        # TODO(vish): this can be removed after data has been updated
        # data doesn't seem to have a working iterator so in doesn't work
        if data.get('owner_id', None) is not None:
            data['user_id'] = data['owner_id']
            data['project_id'] = data['owner_id']
        self.datamodel = data

        size = data.get('instance_type', FLAGS.default_instance_type)
        if size not in INSTANCE_TYPES:
            raise exception.Error('invalid instance type: %s' % size)

        self.datamodel.update(INSTANCE_TYPES[size])

        self.datamodel['name'] = name
        self.datamodel['instance_id'] = name
        self.datamodel['basepath'] = data.get(
                'basepath', os.path.abspath(
                os.path.join(FLAGS.instances_path, self.name)))
        self.datamodel['memory_kb'] = int(self.datamodel['memory_mb']) * 1024
        self.datamodel.setdefault('image_id', FLAGS.default_image)
        self.datamodel.setdefault('kernel_id', FLAGS.default_kernel)
        self.datamodel.setdefault('ramdisk_id', FLAGS.default_ramdisk)
        self.datamodel.setdefault('project_id', self.datamodel['user_id'])
        self.datamodel.setdefault('bridge_name', None)
        #self.datamodel.setdefault('key_data', None)
        #self.datamodel.setdefault('key_name', None)
        #self.datamodel.setdefault('addressing_type', None)

        # TODO(joshua) - The ugly non-flat ones
        self.datamodel['groups'] = data.get('security_group', 'default')
        # TODO(joshua): Support product codes somehow
        self.datamodel.setdefault('product_codes', None)

        self.datamodel.save()
        logging.debug("Finished init of Instance with id of %s" % name)

    def is_pending(self):
        return (self.state == power_state.NOSTATE or self.state == 'pending')

    def is_destroyed(self):
        return self.state == power_state.SHUTOFF

    def is_running(self):
        logging.debug("Instance state is: %s" % self.state)
        return (self.state == power_state.RUNNING or self.state == 'running')

