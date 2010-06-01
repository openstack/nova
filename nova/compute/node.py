# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright [2010] [Anso Labs, LLC]
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""
Compute Node:

    Runs on each compute node, managing the
    hypervisor using libvirt.

"""

import base64
import json
import logging
import os
import random
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
from nova.objectstore import image # for image_path flag

FLAGS = flags.FLAGS
flags.DEFINE_string('libvirt_xml_template',
                        utils.abspath('compute/libvirt.xml.template'),
                        'Network XML Template')
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

# The number of processes to start in our process pool
# TODO(termie): this should probably be a flag and the pool should probably
#               be a singleton
PROCESS_POOL_SIZE = 4

class Node(object, service.Service):
    """
    Manages the running instances.
    """
    def __init__(self):
        """ load configuration options for this node and connect to libvirt """
        super(Node, self).__init__()
        self._instances = {}
        self._conn = self._get_connection()
        self._pool = process.Pool(PROCESS_POOL_SIZE)
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
        # TODO: Get the real security group of launch in here
        security_group = "default"
        net = network.BridgedNetwork.get_network_for_project(inst['user_id'], inst['project_id'],
                                            security_group).express()
        inst['node_name'] = FLAGS.node_name
        inst.save()
        # TODO(vish) check to make sure the availability zone matches
        new_inst = Instance(self._conn, name=instance_id,
                            pool=self._pool, data=inst)
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
                      aoe_device = None, mountpoint = None):
        utils.runthis("Attached Volume: %s",
                "sudo virsh attach-disk %s /dev/etherd/%s %s"
                % (instance_id, aoe_device, mountpoint.split("/")[-1]))
        return defer.succeed(True)

    def _init_aoe(self):
        utils.runthis("Doin an AoE discover, returns %s", "sudo aoe-discover")
        utils.runthis("Doin an AoE stat, returns %s", "sudo aoe-stat")

    @exception.wrap_exception
    def detach_volume(self, instance_id, mountpoint):
        """ detach a volume from an instance """
        # despite the documentation, virsh detach-disk just wants the device
        # name without the leading /dev/
        target = mountpoint.rpartition('/dev/')[2]
        utils.runthis("Detached Volume: %s", "sudo virsh detach-disk %s %s "
                % (instance_id, target))
        return defer.succeed(True)


class Group(object):
    def __init__(self, group_id):
        self.group_id = group_id


class ProductCode(object):
    def __init__(self, product_code):
        self.product_code = product_code


def _create_image(data, libvirt_xml):
    """ create libvirt.xml and copy files into instance path """
    def basepath(path=''):
        return os.path.abspath(os.path.join(data['basepath'], path))

    def imagepath(path=''):
        return os.path.join(FLAGS.images_path, path)

    def image_url(path):
        return "%s:%s/_images/%s" % (FLAGS.s3_host, FLAGS.s3_port, path)
    logging.info(basepath('disk'))
    try:
        os.makedirs(data['basepath'])
        os.chmod(data['basepath'], 0777)
    except OSError:
        # TODO: there is already an instance with this name, do something
        pass
    try:
        logging.info('Creating image for: %s', data['instance_id'])
        f = open(basepath('libvirt.xml'), 'w')
        f.write(libvirt_xml)
        f.close()
        if not FLAGS.fake_libvirt:
            if FLAGS.use_s3:
                if not os.path.exists(basepath('disk')):
                    utils.fetchfile(image_url("%s/image" % data['image_id']),
                       basepath('disk-raw'))
                if not os.path.exists(basepath('kernel')):
                    utils.fetchfile(image_url("%s/image" % data['kernel_id']),
                                basepath('kernel'))
                if not os.path.exists(basepath('ramdisk')):
                    utils.fetchfile(image_url("%s/image" % data['ramdisk_id']),
                           basepath('ramdisk'))
            else:
                if not os.path.exists(basepath('disk')):
                    shutil.copyfile(imagepath("%s/image" % data['image_id']),
                        basepath('disk-raw'))
                if not os.path.exists(basepath('kernel')):
                    shutil.copyfile(imagepath("%s/image" % data['kernel_id']),
                        basepath('kernel'))
                if not os.path.exists(basepath('ramdisk')):
                    shutil.copyfile(imagepath("%s/image" %
                        data['ramdisk_id']),
                        basepath('ramdisk'))
            if data['key_data']:
                logging.info('Injecting key data into image %s' %
                        data['image_id'])
                disk.inject_key(data['key_data'], basepath('disk-raw'))
            if os.path.exists(basepath('disk')):
                os.remove(basepath('disk'))
            bytes = INSTANCE_TYPES[data['instance_type']]['local_gb'] * 1024 * 1024 * 1024
            disk.partition(basepath('disk-raw'), basepath('disk'), bytes)
        logging.info('Done create image for: %s', data['instance_id'])
    except Exception as ex:
        return {'exception': ex}


class Instance(object):

    NOSTATE = 0x00
    RUNNING = 0x01
    BLOCKED = 0x02
    PAUSED = 0x03
    SHUTDOWN = 0x04
    SHUTOFF = 0x05
    CRASHED = 0x06

    def is_pending(self):
        return (self.state == Instance.NOSTATE or self.state == 'pending')

    def is_destroyed(self):
        return self.state == Instance.SHUTOFF

    def is_running(self):
        logging.debug("Instance state is: %s" % self.state)
        return (self.state == Instance.RUNNING or self.state == 'running')

    def __init__(self, conn, pool, name, data):
        """ spawn an instance with a given name """
        # TODO(termie): pool should probably be a singleton instead of being passed
        #               here and in the classmethods
        self._pool = pool
        self._conn = conn
        # TODO(vish): this can be removed after data has been updated
        # data doesn't seem to have a working iterator so in doesn't work
        if not data.get('owner_id', None) is None:
            data['user_id'] = data['owner_id']
            data['project_id'] = data['owner_id']
        self.datamodel = data

        # NOTE(termie): to be passed to multiprocess self._s must be
        #               pickle-able by cPickle
        self._s = {}

        # TODO(termie): is instance_type that actual name for this?
        size = data.get('instance_type', FLAGS.default_instance_type)
        if size not in INSTANCE_TYPES:
            raise exception.Error('invalid instance type: %s' % size)

        self._s.update(INSTANCE_TYPES[size])

        self._s['name'] = name
        self._s['instance_id'] = name
        self._s['instance_type'] = size
        self._s['mac_address'] = data.get(
                'mac_address', 'df:df:df:df:df:df')
        self._s['basepath'] = data.get(
                'basepath', os.path.abspath(
                os.path.join(FLAGS.instances_path, self.name)))
        self._s['memory_kb'] = int(self._s['memory_mb']) * 1024
        self._s['image_id'] = data.get('image_id', FLAGS.default_image)
        self._s['kernel_id'] = data.get('kernel_id', FLAGS.default_kernel)
        self._s['ramdisk_id'] = data.get('ramdisk_id', FLAGS.default_ramdisk)
        self._s['user_id'] = data.get('user_id', None)
        self._s['project_id'] = data.get('project_id', self._s['user_id'])
        self._s['node_name'] = data.get('node_name', '')
        self._s['user_data'] = data.get('user_data', '')
        self._s['ami_launch_index'] = data.get('ami_launch_index', None)
        self._s['launch_time'] = data.get('launch_time', None)
        self._s['reservation_id'] = data.get('reservation_id', None)
        # self._s['state'] = Instance.NOSTATE
        self._s['state'] = data.get('state', Instance.NOSTATE)
        self._s['key_data'] = data.get('key_data', None)

        # TODO: we may not need to save the next few
        self._s['groups'] = data.get('security_group', ['default'])
        self._s['product_codes'] = data.get('product_code', [])
        self._s['key_name'] = data.get('key_name', None)
        self._s['addressing_type'] = data.get('addressing_type', None)
        self._s['availability_zone'] = data.get('availability_zone', 'fixme')

        self._s['bridge_name'] = data.get('bridge_name', None)
        #TODO: put real dns items here
        self._s['private_dns_name'] = data.get('private_dns_name', 'fixme')
        self._s['dns_name'] = data.get('dns_name',
                                self._s['private_dns_name'])
        logging.debug("Finished init of Instance with id of %s" % name)

    def toXml(self):
        # TODO(termie): cache?
        logging.debug("Starting the toXML method")
        libvirt_xml = open(FLAGS.libvirt_xml_template).read()
        xml_info = self._s.copy()
        #xml_info.update(self._s)

        # TODO(termie): lazy lazy hack because xml is annoying
        xml_info['nova'] = json.dumps(self._s)
        libvirt_xml = libvirt_xml % xml_info
        logging.debug("Finished the toXML method")

        return libvirt_xml

    @classmethod
    def fromName(cls, conn, pool, name):
        """ use the saved data for reloading the instance """
        # if FLAGS.fake_libvirt:
        #     raise Exception('this is a bit useless, eh?')

        instdir = model.InstanceDirectory()
        instance = instdir.get(name)
        return cls(conn=conn, pool=pool, name=name, data=instance)

    @property
    def state(self):
        return self._s['state']

    @property
    def name(self):
        return self._s['name']

    def describe(self):
        return self._s

    def info(self):
        logging.debug("Getting info for dom %s" % self.name)
        virt_dom = self._conn.lookupByName(self.name)
        (state, max_mem, mem, num_cpu, cpu_time) = virt_dom.info()
        return {'state': state,
                'max_mem': max_mem,
                'mem': mem,
                'num_cpu': num_cpu,
                'cpu_time': cpu_time}

    def update_state(self):
        info = self.info()
        self.datamodel['state'] = info['state']
        self.datamodel['node_name'] = FLAGS.node_name
        self.datamodel.save()

    @exception.wrap_exception
    def destroy(self):
        if self.is_destroyed():
            self.datamodel.destroy()
            raise exception.Error('trying to destroy already destroyed'
                                  ' instance: %s' % self.name)

        self.datamodel['state'] = 'shutting_down'
        self.datamodel.save()
        try:
            virt_dom = self._conn.lookupByName(self.name)
            virt_dom.destroy()
        except Exception, _err:
            pass
            # If the instance is already terminated, we're still happy
        d = defer.Deferred()
        d.addCallback(lambda x: self.datamodel.destroy())
        # TODO(termie): short-circuit me for tests
        # WE'LL save this for when we do shutdown,
        # instead of destroy - but destroy returns immediately
        timer = task.LoopingCall(f=None)
        def _wait_for_shutdown():
            try:
                info = self.info()
                if info['state'] == Instance.SHUTDOWN:
                    self._s['state'] = Instance.SHUTDOWN
                    #self.datamodel['state'] = 'shutdown'
                    #self.datamodel.save()
                    timer.stop()
                    d.callback(None)
            except Exception:
                self._s['state'] = Instance.SHUTDOWN
                timer.stop()
                d.callback(None)
        timer.f = _wait_for_shutdown
        timer.start(interval=0.5, now=True)
        return d

    @defer.inlineCallbacks
    @exception.wrap_exception
    def reboot(self):
        # if not self.is_running():
        #     raise exception.Error(
        #             'trying to reboot a non-running'
        #             'instance: %s (state: %s)' % (self.name, self.state))

        yield self._conn.lookupByName(self.name).destroy()
        self.datamodel['state'] = 'rebooting'
        self.datamodel.save()
        self._s['state'] = Instance.NOSTATE
        self._conn.createXML(self.toXml(), 0)
        # TODO(termie): this should actually register a callback to check
        #               for successful boot
        self.datamodel['state'] = 'running'
        self.datamodel.save()
        self._s['state'] = Instance.RUNNING
        logging.debug('rebooted instance %s' % self.name)
        defer.returnValue(None)

    # @exception.wrap_exception
    def spawn(self):
        self.datamodel['state'] = "spawning"
        self.datamodel.save()
        logging.debug("Starting spawn in Instance")
        xml = self.toXml()
        def _launch(retvals):
            self.datamodel['state'] = 'launching'
            self.datamodel.save()
            try:
                logging.debug("Arrived in _launch")
                if retvals and 'exception' in retvals:
                    raise retvals['exception']
                self._conn.createXML(self.toXml(), 0)
                # TODO(termie): this should actually register
                # a callback to check for successful boot
                self._s['state'] = Instance.RUNNING
                self.datamodel['state'] = 'running'
                self.datamodel.save()
                logging.debug("Instance is running")
            except Exception as ex:
                logging.debug(ex)
                self.datamodel['state'] = 'shutdown'
                self.datamodel.save()
                #return self

        d = self._pool.apply(_create_image, self._s, xml)
        d.addCallback(_launch)
        return d

    @exception.wrap_exception
    def console_output(self):
        if not FLAGS.fake_libvirt:
            fname = os.path.abspath(
                    os.path.join(self._s['basepath'], 'console.log'))
            with open(fname, 'r') as f:
                console = f.read()
        else:
            console = 'FAKE CONSOLE OUTPUT'
        return defer.succeed(console)
