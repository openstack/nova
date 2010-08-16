# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
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
A connection to a hypervisor (e.g. KVM) through libvirt.
"""

import json
import logging
import os.path
import shutil

from twisted.internet import defer
from twisted.internet import task

from nova import exception
from nova import flags
from nova import process
from nova import utils
from nova.auth import manager
from nova.compute import disk
from nova.compute import instance_types
from nova.compute import power_state
from nova.virt import images

libvirt = None
libxml2 = None


FLAGS = flags.FLAGS
flags.DEFINE_string('libvirt_xml_template',
                    utils.abspath('virt/libvirt.qemu.xml.template'),
                    'Libvirt XML Template for QEmu/KVM')
flags.DEFINE_string('libvirt_uml_xml_template',
                    utils.abspath('virt/libvirt.uml.xml.template'),
                    'Libvirt XML Template for user-mode-linux')
flags.DEFINE_string('injected_network_template',
                    utils.abspath('virt/interfaces.template'),
                    'Template file for injected network')
flags.DEFINE_string('libvirt_type',
                    'kvm',
                    'Libvirt domain type (valid options are: kvm, qemu, uml)')
flags.DEFINE_string('libvirt_uri',
                    '',
                    'Override the default libvirt URI (which is dependent'
                    ' on libvirt_type)')


def get_connection(read_only):
    # These are loaded late so that there's no need to install these
    # libraries when not using libvirt.
    global libvirt
    global libxml2
    if libvirt is None:
        libvirt = __import__('libvirt')
    if libxml2 is None:
        libxml2 = __import__('libxml2')
    return LibvirtConnection(read_only)


class LibvirtConnection(object):
    def __init__(self, read_only):
        self.libvirt_uri, template_file = self.get_uri_and_template()

        self.libvirt_xml = open(template_file).read()
        self._wrapped_conn = None
        self.read_only = read_only

    @property
    def _conn(self):
        if not self._wrapped_conn:
            self._wrapped_conn = self._connect(self.libvirt_uri, self.read_only)
        return self._wrapped_conn

    def get_uri_and_template(self):
        if FLAGS.libvirt_type == 'uml':
            uri = FLAGS.libvirt_uri or 'uml:///system'
            template_file = FLAGS.libvirt_uml_xml_template
        else:
            uri = FLAGS.libvirt_uri or 'qemu:///system'
            template_file = FLAGS.libvirt_xml_template
        return uri, template_file

    def _connect(self, uri, read_only):
        auth = [[libvirt.VIR_CRED_AUTHNAME, libvirt.VIR_CRED_NOECHOPROMPT],
                'root',
                None]

        if read_only:
            return libvirt.openReadOnly(uri)
        else:
            return libvirt.openAuth(uri, auth, 0)

    def list_instances(self):
        return [self._conn.lookupByID(x).name()
                for x in self._conn.listDomainsID()]

    def destroy(self, instance):
        try:
            virt_dom = self._conn.lookupByName(instance.name)
            virt_dom.destroy()
        except Exception, _err:
            pass
            # If the instance is already terminated, we're still happy
        d = defer.Deferred()
        d.addCallback(lambda _: self._cleanup(instance))
        # FIXME: What does this comment mean?
        # TODO(termie): short-circuit me for tests
        # WE'LL save this for when we do shutdown,
        # instead of destroy - but destroy returns immediately
        timer = task.LoopingCall(f=None)
        def _wait_for_shutdown():
            try:
                instance.update_state()
                if instance.state == power_state.SHUTDOWN:
                    timer.stop()
                    d.callback(None)
            except Exception:
                instance.set_state(power_state.SHUTDOWN)
                timer.stop()
                d.callback(None)
        timer.f = _wait_for_shutdown
        timer.start(interval=0.5, now=True)
        return d

    def _cleanup(self, instance):
        target = os.path.abspath(instance.datamodel['basepath'])
        logging.info("Deleting instance files at %s", target)
        if os.path.exists(target):
            shutil.rmtree(target)

    @defer.inlineCallbacks
    @exception.wrap_exception
    def reboot(self, instance):
        xml = self.toXml(instance)
        yield self._conn.lookupByName(instance.name).destroy()
        yield self._conn.createXML(xml, 0)

        d = defer.Deferred()
        timer = task.LoopingCall(f=None)
        def _wait_for_reboot():
            try:
                instance.update_state()
                if instance.is_running():
                    logging.debug('rebooted instance %s' % instance.name)
                    timer.stop()
                    d.callback(None)
            except Exception, exn:
                logging.error('_wait_for_reboot failed: %s' % exn)
                instance.set_state(power_state.SHUTDOWN)
                timer.stop()
                d.callback(None)
        timer.f = _wait_for_reboot
        timer.start(interval=0.5, now=True)
        yield d

    @defer.inlineCallbacks
    @exception.wrap_exception
    def spawn(self, instance):
        xml = self.toXml(instance)
        instance.set_state(power_state.NOSTATE, 'launching')
        yield self._create_image(instance, xml)
        yield self._conn.createXML(xml, 0)
        # TODO(termie): this should actually register
        # a callback to check for successful boot
        logging.debug("Instance is running")

        local_d = defer.Deferred()
        timer = task.LoopingCall(f=None)
        def _wait_for_boot():
            try:
                instance.update_state()
                if instance.is_running():
                    logging.debug('booted instance %s' % instance.name)
                    timer.stop()
                    local_d.callback(None)
            except Exception, exn:
                logging.error("_wait_for_boot exception %s" % exn)
                self.set_state(power_state.SHUTDOWN)
                logging.error('Failed to boot instance %s' % instance.name)
                timer.stop()
                local_d.callback(None)
        timer.f = _wait_for_boot
        timer.start(interval=0.5, now=True)
        yield local_d

    @defer.inlineCallbacks
    def _create_image(self, instance, libvirt_xml):
        # syntactic nicety
        data = instance.datamodel
        basepath = lambda x='': self.basepath(instance, x)

        # ensure directories exist and are writable
        yield process.simple_execute('mkdir -p %s' % basepath())
        yield process.simple_execute('chmod 0777 %s' % basepath())


        # TODO(termie): these are blocking calls, it would be great
        #               if they weren't.
        logging.info('Creating image for: %s', data['instance_id'])
        f = open(basepath('libvirt.xml'), 'w')
        f.write(libvirt_xml)
        f.close()

        user = manager.AuthManager().get_user(data['user_id'])
        project = manager.AuthManager().get_project(data['project_id'])
        if not os.path.exists(basepath('disk')):
           yield images.fetch(data['image_id'], basepath('disk-raw'), user, project)
        if not os.path.exists(basepath('kernel')):
           yield images.fetch(data['kernel_id'], basepath('kernel'), user, project)
        if not os.path.exists(basepath('ramdisk')):
           yield images.fetch(data['ramdisk_id'], basepath('ramdisk'), user, project)

        execute = lambda cmd, input=None: \
                  process.simple_execute(cmd=cmd,
                                         input=input,
                                         error_ok=1)

        key = data['key_data']
        net = None
        if data.get('inject_network', False):
            with open(FLAGS.injected_network_template) as f:
                net = f.read() % {'address': data['private_dns_name'],
                                  'network': data['network_network'],
                                  'netmask': data['network_netmask'],
                                  'gateway': data['network_gateway'],
                                  'broadcast': data['network_broadcast'],
                                  'dns': data['network_dns']}
        if key or net:
            logging.info('Injecting data into image %s', data['image_id'])
            yield disk.inject_data(basepath('disk-raw'), key, net, execute=execute)

        if os.path.exists(basepath('disk')):
            yield process.simple_execute('rm -f %s' % basepath('disk'))

        bytes = (instance_types.INSTANCE_TYPES[data['instance_type']]['local_gb']
                 * 1024 * 1024 * 1024)
        yield disk.partition(
                basepath('disk-raw'), basepath('disk'), bytes, execute=execute)

    def basepath(self, instance, path=''):
        return os.path.abspath(os.path.join(instance.datamodel['basepath'], path))

    def toXml(self, instance):
        # TODO(termie): cache?
        logging.debug("Starting the toXML method")
        xml_info = instance.datamodel.copy()
        # TODO(joshua): Make this xml express the attached disks as well

        # TODO(termie): lazy lazy hack because xml is annoying
        xml_info['nova'] = json.dumps(instance.datamodel.copy())
        xml_info['type'] = FLAGS.libvirt_type
        libvirt_xml = self.libvirt_xml % xml_info
        logging.debug("Finished the toXML method")

        return libvirt_xml

    def get_info(self, instance_id):
        virt_dom = self._conn.lookupByName(instance_id)
        (state, max_mem, mem, num_cpu, cpu_time) = virt_dom.info()
        return {'state': state,
                'max_mem': max_mem,
                'mem': mem,
                'num_cpu': num_cpu,
                'cpu_time': cpu_time}

    def get_disks(self, instance_id):
        """
        Note that this function takes an instance ID, not an Instance, so
        that it can be called by monitor.

        Returns a list of all block devices for this domain.
        """
        domain = self._conn.lookupByName(instance_id)
        # TODO(devcamcar): Replace libxml2 with etree.
        xml = domain.XMLDesc(0)
        doc = None

        try:
            doc = libxml2.parseDoc(xml)
        except:
            return []

        ctx = doc.xpathNewContext()
        disks = []

        try:
            ret = ctx.xpathEval('/domain/devices/disk')

            for node in ret:
                devdst = None

                for child in node.children:
                    if child.name == 'target':
                        devdst = child.prop('dev')

                if devdst == None:
                    continue

                disks.append(devdst)
        finally:
            if ctx != None:
                ctx.xpathFreeContext()
            if doc != None:
                doc.freeDoc()

        return disks

    def get_interfaces(self, instance_id):
        """
        Note that this function takes an instance ID, not an Instance, so
        that it can be called by monitor.

        Returns a list of all network interfaces for this instance.
        """
        domain = self._conn.lookupByName(instance_id)
        # TODO(devcamcar): Replace libxml2 with etree.
        xml = domain.XMLDesc(0)
        doc = None

        try:
            doc = libxml2.parseDoc(xml)
        except:
            return []

        ctx = doc.xpathNewContext()
        interfaces = []

        try:
            ret = ctx.xpathEval('/domain/devices/interface')

            for node in ret:
                devdst = None

                for child in node.children:
                    if child.name == 'target':
                        devdst = child.prop('dev')

                if devdst == None:
                    continue

                interfaces.append(devdst)
        finally:
            if ctx != None:
                ctx.xpathFreeContext()
            if doc != None:
                doc.freeDoc()

        return interfaces

    def block_stats(self, instance_id, disk):
        """
        Note that this function takes an instance ID, not an Instance, so
        that it can be called by monitor.
        """
        domain = self._conn.lookupByName(instance_id)
        return domain.blockStats(disk)

    def interface_stats(self, instance_id, interface):
        """
        Note that this function takes an instance ID, not an Instance, so
        that it can be called by monitor.
        """
        domain = self._conn.lookupByName(instance_id)
        return domain.interfaceStats(interface)
