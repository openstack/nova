# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
# Copyright 2010 Anso Labs, LLC
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
Compute Node:

    Runs on each compute node, managing the
    hypervisor using libvirt.

"""

import base64
import json
import logging
import os
import shutil
import sys

from nova import vendor
from twisted.internet import defer
from twisted.internet import task
from twisted.application import service

try:
    import libvirt
except Exception, err:
    logging.warning('no libvirt found')

from nova import exception
from nova import fakevirt
from nova import flags
from nova import process
from nova import utils
from nova.compute import disk
from nova.compute import model
from nova.compute import network
from nova.volume import storage
from nova.objectstore import image # for image_path flag

FLAGS = flags.FLAGS
flags.DEFINE_string('libvirt_xml_template',
                        utils.abspath('compute/libvirt.xml.template'),
                        'Libvirt XML Template')
flags.DEFINE_bool('use_s3', True,
                      'whether to get images from s3 or use local copy')
flags.DEFINE_string('instances_path', utils.abspath('../instances'),
                        'where instances are stored on disk')

INSTANCE_TYPES = {}
INSTANCE_TYPES['m1.tiny'] = {'memory_mb': 512, 'vcpus': 1, 'local_gb': 0}
INSTANCE_TYPES['m1.small'] = {'memory_mb': 1024, 'vcpus': 1, 'local_gb': 10}
INSTANCE_TYPES['m1.medium'] = {'memory_mb': 2048, 'vcpus': 2, 'local_gb': 10}
INSTANCE_TYPES['m1.large'] = {'memory_mb': 4096, 'vcpus': 4, 'local_gb': 10}
INSTANCE_TYPES['m1.xlarge'] = {'memory_mb': 8192, 'vcpus': 4, 'local_gb': 10}
INSTANCE_TYPES['c1.medium'] = {'memory_mb': 2048, 'vcpus': 4, 'local_gb': 10}


def _image_path(path=''):
    return os.path.join(FLAGS.images_path, path)


def _image_url(path):
    return "%s:%s/_images/%s" % (FLAGS.s3_host, FLAGS.s3_port, path)


class Node(object, service.Service):
    """
    Manages the running instances.
    """
    def __init__(self):
        """ load configuration options for this node and connect to libvirt """
        super(Node, self).__init__()
        self._instances = {}
        self._conn = self._get_connection()
        self._pool = process.ProcessPool()
        self.instdir = model.InstanceDirectory()
        # TODO(joshua): This needs to ensure system state, specifically: modprobe aoe

    def _get_connection(self):
        """ returns a libvirt connection object """
        # TODO(termie): maybe lazy load after initial check for permissions
        # TODO(termie): check whether we can be disconnected
        if FLAGS.fake_libvirt:
            conn = fakevirt.FakeVirtConnection.instance()
        else:
            auth = [[libvirt.VIR_CRED_AUTHNAME, libvirt.VIR_CRED_NOECHOPROMPT],
                    'root',
                    None]
            conn = libvirt.openAuth('qemu:///system', auth, 0)
            if conn == None:
                logging.error('Failed to open connection to the hypervisor')
                sys.exit(1)
        return conn

    def noop(self):
        """ simple test of an AMQP message call """
        return defer.succeed('PONG')

    def get_instance(self, instance_id):
        # inst = self.instdir.get(instance_id)
        # return inst
        if self.instdir.exists(instance_id):
            return Instance.fromName(self._conn, self._pool, instance_id)
        return None

    @exception.wrap_exception
    def adopt_instances(self):
        """ if there are instances already running, adopt them """
        return defer.succeed(0)
        instance_names = [self._conn.lookupByID(x).name()
                          for x in self._conn.listDomainsID()]
        for name in instance_names:
            try:
                new_inst = Instance.fromName(self._conn, self._pool, name)
                new_inst.update_state()
            except:
                pass
        return defer.succeed(len(self._instances))

    @exception.wrap_exception
    def describe_instances(self):
        retval = {}
        for inst in self.instdir.by_node(FLAGS.node_name):
            retval[inst['instance_id']] = (Instance.fromName(self._conn, self._pool, inst['instance_id']))
        return retval

    @defer.inlineCallbacks
    def report_state(self):
        logging.debug("Reporting State")
        return

    # @exception.wrap_exception
    def run_instance(self, instance_id, **_kwargs):
        """ launch a new instance with specified options """
        logging.debug("Starting instance %s..." % (instance_id))
        inst = self.instdir.get(instance_id)
        if not FLAGS.simple_network:
            # TODO: Get the real security group of launch in here
            security_group = "default"
            net = network.BridgedNetwork.get_network_for_project(inst['user_id'],
                                                             inst['project_id'],
                                            security_group).express()
        inst['node_name'] = FLAGS.node_name
        inst.save()
        # TODO(vish) check to make sure the availability zone matches
        new_inst = Instance(self._conn, name=instance_id,
                            pool=self._pool, data=inst)
        logging.info("Instances current state is %s", new_inst.state)
        if new_inst.is_running():
            raise exception.Error("Instance is already running")
        d = new_inst.spawn()
        return d

    @exception.wrap_exception
    def terminate_instance(self, instance_id):
        """ terminate an instance on this machine """
        logging.debug("Got told to terminate instance %s" % instance_id)
        instance = self.get_instance(instance_id)
        # inst = self.instdir.get(instance_id)
        if not instance:
            raise exception.Error(
                    'trying to terminate unknown instance: %s' % instance_id)
        d = instance.destroy()
        # d.addCallback(lambda x: inst.destroy())
        return d

    @exception.wrap_exception
    def reboot_instance(self, instance_id):
        """ reboot an instance on this server
        KVM doesn't support reboot, so we terminate and restart """
        instance = self.get_instance(instance_id)
        if not instance:
            raise exception.Error(
                    'trying to reboot unknown instance: %s' % instance_id)
        return instance.reboot()

    @defer.inlineCallbacks
    @exception.wrap_exception
    def get_console_output(self, instance_id):
        """ send the console output for an instance """
        logging.debug("Getting console output for %s" % (instance_id))
        inst = self.instdir.get(instance_id)
        instance = self.get_instance(instance_id)
        if not instance:
            raise exception.Error(
                    'trying to get console log for unknown: %s' % instance_id)
        rv = yield instance.console_output()
        # TODO(termie): this stuff belongs in the API layer, no need to
        #               munge the data we send to ourselves
        output = {"InstanceId" : instance_id,
                  "Timestamp" : "2",
                  "output" : base64.b64encode(rv)}
        defer.returnValue(output)

    @defer.inlineCallbacks
    @exception.wrap_exception
    def attach_volume(self, instance_id = None,
                      volume_id = None, mountpoint = None):
        volume = storage.get_volume(volume_id)
        yield self._init_aoe()
        yield utils.runthis("Attached Volume: %s",
                "sudo virsh attach-disk %s /dev/etherd/%s %s"
                % (instance_id, volume['aoe_device'], mountpoint.split("/")[-1]))
        volume.finish_attach()
        defer.returnValue(True)

    def _init_aoe(self):
        utils.runthis("Doin an AoE discover, returns %s", "sudo aoe-discover")
        utils.runthis("Doin an AoE stat, returns %s", "sudo aoe-stat")

    @exception.wrap_exception
    def detach_volume(self, instance_id, volume_id):
        """ detach a volume from an instance """
        # despite the documentation, virsh detach-disk just wants the device
        # name without the leading /dev/
        volume = storage.get_volume(volume_id)
        target = volume['mountpoint'].rpartition('/dev/')[2]
        utils.runthis("Detached Volume: %s", "sudo virsh detach-disk %s %s "
                % (instance_id, target))
        volume.finish_detach()
        return defer.succeed(True)


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

    def __init__(self, conn, pool, name, data):
        """ spawn an instance with a given name """
        # TODO(termie): pool should probably be a singleton instead of being passed
        #               here and in the classmethods
        self._pool = pool
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

    def toXml(self):
        # TODO(termie): cache?
        logging.debug("Starting the toXML method")
        libvirt_xml = open(FLAGS.libvirt_xml_template).read()
        xml_info = self.datamodel.copy()
        # TODO(joshua): Make this xml express the attached disks as well

        # TODO(termie): lazy lazy hack because xml is annoying
        xml_info['nova'] = json.dumps(self.datamodel.copy())
        libvirt_xml = libvirt_xml % xml_info
        logging.debug("Finished the toXML method")

        return libvirt_xml

    @classmethod
    def fromName(cls, conn, pool, name):
        """ use the saved data for reloading the instance """
        instdir = model.InstanceDirectory()
        instance = instdir.get(name)
        return cls(conn=conn, pool=pool, name=name, data=instance)

    def set_state(self, state_code, state_description=None):
        self.datamodel['state'] = state_code
        if not state_description:
            state_description = STATE_NAMES[state_code]
        self.datamodel['state_description'] = state_description
        self.datamodel.save()

    @property
    def state(self):
        # it is a string in datamodel
        return int(self.datamodel['state'])

    @property
    def name(self):
        return self.datamodel['name']

    def is_pending(self):
        return (self.state == Instance.NOSTATE or self.state == 'pending')

    def is_destroyed(self):
        return self.state == Instance.SHUTOFF

    def is_running(self):
        logging.debug("Instance state is: %s" % self.state)
        return (self.state == Instance.RUNNING or self.state == 'running')

    def describe(self):
        return self.datamodel

    def info(self):
        logging.debug("Getting info for dom %s" % self.name)
        virt_dom = self._conn.lookupByName(self.name)
        (state, max_mem, mem, num_cpu, cpu_time) = virt_dom.info()
        return {'state': state,
                'max_mem': max_mem,
                'mem': mem,
                'num_cpu': num_cpu,
                'cpu_time': cpu_time,
                'node_name': FLAGS.node_name}

    def basepath(self, path=''):
        return os.path.abspath(os.path.join(self.datamodel['basepath'], path))

    def update_state(self):
        self.datamodel.update(self.info())
        self.set_state(self.state)
        self.datamodel.save() # Extra, but harmless

    @exception.wrap_exception
    def destroy(self):
        if self.is_destroyed():
            self.datamodel.destroy()
            raise exception.Error('trying to destroy already destroyed'
                                  ' instance: %s' % self.name)

        self.set_state(Instance.NOSTATE, 'shutting_down')
        try:
            virt_dom = self._conn.lookupByName(self.name)
            virt_dom.destroy()
        except Exception, _err:
            pass
            # If the instance is already terminated, we're still happy
        d = defer.Deferred()
        d.addCallback(lambda x: self._cleanup())
        d.addCallback(lambda x: self.datamodel.destroy())
        # TODO(termie): short-circuit me for tests
        # WE'LL save this for when we do shutdown,
        # instead of destroy - but destroy returns immediately
        timer = task.LoopingCall(f=None)
        def _wait_for_shutdown():
            try:
                self.update_state()
                if self.state == Instance.SHUTDOWN:
                    timer.stop()
                    d.callback(None)
            except Exception:
                self.set_state(Instance.SHUTDOWN)
                timer.stop()
                d.callback(None)
        timer.f = _wait_for_shutdown
        timer.start(interval=0.5, now=True)
        return d

    def _cleanup(self):
        target = os.path.abspath(self.datamodel['basepath'])
        logging.info("Deleting instance files at %s", target)
        shutil.rmtree(target)

    @defer.inlineCallbacks
    @exception.wrap_exception
    def reboot(self):
        if not self.is_running():
            raise exception.Error(
                    'trying to reboot a non-running'
                    'instance: %s (state: %s)' % (self.name, self.state))

        logging.debug('rebooting instance %s' % self.name)
        self.set_state(Instance.NOSTATE, 'rebooting')
        yield self._conn.lookupByName(self.name).destroy()
        self._conn.createXML(self.toXml(), 0)

        d = defer.Deferred()
        timer = task.LoopingCall(f=None)
        def _wait_for_reboot():
            try:
                self.update_state()
                if self.is_running():
                    logging.debug('rebooted instance %s' % self.name)
                    timer.stop()
                    d.callback(None)
            except Exception:
                self.set_state(Instance.SHUTDOWN)
                timer.stop()
                d.callback(None)
        timer.f = _wait_for_reboot
        timer.start(interval=0.5, now=True)
        yield d

    def _fetch_s3_image(self, image, path):
        url = _image_url('%s/image' % image)
        d = self._pool.simpleExecute('curl --silent %s -o %s' % (url, path))
        return d

    def _fetch_local_image(self, image, path):
        source = _image_path('%s/image' % image)
        d = self._pool.simpleExecute('cp %s %s' % (source, path))
        return d

    @defer.inlineCallbacks
    def _create_image(self, libvirt_xml):
        # syntactic nicety
        data = self.datamodel
        basepath = self.basepath

        # ensure directories exist and are writable
        yield self._pool.simpleExecute('mkdir -p %s' % basepath())
        yield self._pool.simpleExecute('chmod 0777 %s' % basepath())


        # TODO(termie): these are blocking calls, it would be great
        #               if they weren't.
        logging.info('Creating image for: %s', data['instance_id'])
        f = open(basepath('libvirt.xml'), 'w')
        f.write(libvirt_xml)
        f.close()

        if FLAGS.fake_libvirt:
            logging.info('fake_libvirt, nothing to do for create_image')
            raise defer.returnValue(None);

        if FLAGS.use_s3:
            _fetch_file = self._fetch_s3_image
        else:
            _fetch_file = self._fetch_local_image

        if not os.path.exists(basepath('disk')):
           yield _fetch_file(data['image_id'], basepath('disk-raw'))
        if not os.path.exists(basepath('kernel')):
           yield _fetch_file(data['kernel_id'], basepath('kernel'))
        if not os.path.exists(basepath('ramdisk')):
           yield _fetch_file(data['ramdisk_id'], basepath('ramdisk'))

        execute = lambda cmd, input=None: self._pool.simpleExecute(cmd=cmd,
                                                                   input=input,
                                                                   error_ok=1)

        key = data['key_data']
        net = None
        if FLAGS.simple_network:
            with open(FLAGS.simple_network_template) as f:
                net = f.read() % {'address': data['private_dns_name'],
                                  'network': FLAGS.simple_network_network,
                                  'netmask': FLAGS.simple_network_netmask,
                                  'gateway': FLAGS.simple_network_gateway,
                                  'broadcast': FLAGS.simple_network_broadcast,
                                  'dns': FLAGS.simple_network_dns}
        if key or net:
            logging.info('Injecting data into image %s', data['image_id'])
            yield disk.inject_data(basepath('disk-raw'), key, net, execute=execute)

        if os.path.exists(basepath('disk')):
            yield self._pool.simpleExecute('rm -f %s' % basepath('disk'))

        bytes = (INSTANCE_TYPES[data['instance_type']]['local_gb']
                 * 1024 * 1024 * 1024)
        yield disk.partition(
                basepath('disk-raw'), basepath('disk'), bytes, execute=execute)

    @defer.inlineCallbacks
    @exception.wrap_exception
    def spawn(self):
        self.set_state(Instance.NOSTATE, 'spawning')
        logging.debug("Starting spawn in Instance")

        xml = self.toXml()
        self.set_state(Instance.NOSTATE, 'launching')
        logging.info('self %s', self)
        try:
            yield self._create_image(xml)
            self._conn.createXML(xml, 0)
            # TODO(termie): this should actually register
            # a callback to check for successful boot
            logging.debug("Instance is running")

            local_d = defer.Deferred()
            timer = task.LoopingCall(f=None)
            def _wait_for_boot():
                try:
                    self.update_state()
                    if self.is_running():
                        logging.debug('booted instance %s' % self.name)
                        timer.stop()
                        local_d.callback(None)
                except Exception:
                    self.set_state(Instance.SHUTDOWN)
                    logging.error('Failed to boot instance %s' % self.name)
                    timer.stop()
                    local_d.callback(None)
            timer.f = _wait_for_boot
            timer.start(interval=0.5, now=True)
        except Exception, ex:
            logging.debug(ex)
            self.set_state(Instance.SHUTDOWN)

    @exception.wrap_exception
    def console_output(self):
        if not FLAGS.fake_libvirt:
            fname = os.path.abspath(
                    os.path.join(self.datamodel['basepath'], 'console.log'))
            with open(fname, 'r') as f:
                console = f.read()
        else:
            console = 'FAKE CONSOLE OUTPUT'
        return defer.succeed(console)

STATE_NAMES = {
 Instance.NOSTATE : 'pending',
 Instance.RUNNING : 'running',
 Instance.BLOCKED : 'blocked',
 Instance.PAUSED  : 'paused',
 Instance.SHUTDOWN : 'shutdown',
 Instance.SHUTOFF : 'shutdown',
 Instance.CRASHED : 'crashed',
}
