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
A connection to a hypervisor through libvirt.

Supports KVM, QEMU, UML, and XEN.

**Related Flags**

:libvirt_type:  Libvirt domain type.  Can be kvm, qemu, uml, xen
                (default: kvm).
:libvirt_uri:  Override for the default libvirt URI (depends on libvirt_type).
:libvirt_xml_template:  Libvirt XML Template (QEmu/KVM).
:libvirt_xen_xml_template:  Libvirt XML Template (Xen).
:libvirt_uml_xml_template:  Libvirt XML Template (User Mode Linux).
:libvirt_rescue_xml_template:  XML template for rescue mode (KVM & QEMU).
:libvirt_rescue_xen_xml_template:  XML templage for rescue mode (XEN).
:libvirt_rescue_uml_xml_template:  XML template for rescue mode (UML).
:rescue_image_id:  Rescue ami image (default: ami-rescue).
:rescue_kernel_id:  Rescue aki image (default: aki-rescue).
:rescue_ramdisk_id:  Rescue ari image (default: ari-rescue).
:injected_network_template:  Template file for injected network
:allow_project_net_traffic:  Whether to allow in project network traffic

"""

import logging
import os
import shutil

import IPy
from twisted.internet import defer
from twisted.internet import task
from twisted.internet import threads

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import process
from nova import utils
#from nova.api import context
from nova.auth import manager
from nova.compute import disk
from nova.compute import instance_types
from nova.compute import power_state
from nova.virt import images

libvirt = None
libxml2 = None


FLAGS = flags.FLAGS
flags.DEFINE_string('libvirt_rescue_xml_template',
                    utils.abspath('virt/libvirt.rescue.qemu.xml.template'),
                    'Libvirt RESCUE XML Template for QEmu/KVM')
flags.DEFINE_string('libvirt_rescue_xen_xml_template',
                    utils.abspath('virt/libvirt.rescue.xen.xml.template'),
                    'Libvirt RESCUE XML Template for xen')
flags.DEFINE_string('libvirt_rescue_uml_xml_template',
                    utils.abspath('virt/libvirt.rescue.uml.xml.template'),
                    'Libvirt RESCUE XML Template for user-mode-linux')
# TODO(vish): These flags should probably go into a shared location
flags.DEFINE_string('rescue_image_id', 'ami-rescue', 'Rescue ami image')
flags.DEFINE_string('rescue_kernel_id', 'aki-rescue', 'Rescue aki image')
flags.DEFINE_string('rescue_ramdisk_id', 'ari-rescue', 'Rescue ari image')
flags.DEFINE_string('libvirt_xml_template',
                    utils.abspath('virt/libvirt.qemu.xml.template'),
                    'Libvirt XML Template for QEmu/KVM')
flags.DEFINE_string('libvirt_xen_xml_template',
                    utils.abspath('virt/libvirt.xen.xml.template'),
                    'Libvirt XML Template for Xen')
flags.DEFINE_string('libvirt_uml_xml_template',
                    utils.abspath('virt/libvirt.uml.xml.template'),
                    'Libvirt XML Template for user-mode-linux')
flags.DEFINE_string('injected_network_template',
                    utils.abspath('virt/interfaces.template'),
                    'Template file for injected network')
flags.DEFINE_string('libvirt_type',
                    'kvm',
                    'Libvirt domain type (valid options are: '
                    'kvm, qemu, uml, xen)')
flags.DEFINE_string('libvirt_uri',
                    '',
                    'Override the default libvirt URI (which is dependent'
                    ' on libvirt_type)')
flags.DEFINE_bool('allow_project_net_traffic',
                  True,
                  'Whether to allow in project network traffic')
flags.DEFINE_string('firewall_driver', 'nova.virt.libvirt_conn.IptablesFirewallDriver',
                  'Firewall driver (defaults to nwfilter)')


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
        (self.libvirt_uri,
         template_file,
         rescue_file) = self.get_uri_and_templates()

        self.libvirt_xml = open(template_file).read()
        self.rescue_xml = open(rescue_file).read()
        self._wrapped_conn = None
        self.read_only = read_only

        self.nwfilter = NWFilterFirewall(self._get_connection)

        if not FLAGS.firewall_driver:
            self.firewall_driver = self.nwfilter
            self.nwfilter.handle_security_groups = True
        else:
            self.firewall_driver = utils.import_object(FLAGS.firewall_driver)

    def _get_connection(self):
        if not self._wrapped_conn or not self._test_connection():
            logging.debug('Connecting to libvirt: %s' % self.libvirt_uri)
            self._wrapped_conn = self._connect(self.libvirt_uri,
                                               self.read_only)
        return self._wrapped_conn
    _conn = property(_get_connection)

    def _test_connection(self):
        try:
            self._wrapped_conn.getInfo()
            return True
        except libvirt.libvirtError as e:
            if e.get_error_code() == libvirt.VIR_ERR_SYSTEM_ERROR and \
               e.get_error_domain() == libvirt.VIR_FROM_REMOTE:
                logging.debug('Connection to libvirt broke')
                return False
            raise

    def get_uri_and_templates(self):
        if FLAGS.libvirt_type == 'uml':
            uri = FLAGS.libvirt_uri or 'uml:///system'
            template_file = FLAGS.libvirt_uml_xml_template
            rescue_file = FLAGS.libvirt_rescue_uml_xml_template
        elif FLAGS.libvirt_type == 'xen':
            uri = FLAGS.libvirt_uri or 'xen:///'
            template_file = FLAGS.libvirt_xen_xml_template
            rescue_file = FLAGS.libvirt_rescue_xen_xml_template
        else:
            uri = FLAGS.libvirt_uri or 'qemu:///system'
            template_file = FLAGS.libvirt_xml_template
            rescue_file = FLAGS.libvirt_rescue_xml_template
        return uri, template_file, rescue_file

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

    def destroy(self, instance, cleanup=True):
        try:
            virt_dom = self._conn.lookupByName(instance['name'])
            virt_dom.destroy()
        except Exception as _err:
            pass
            # If the instance is already terminated, we're still happy
        d = defer.Deferred()
        if cleanup:
            d.addCallback(lambda _: self._cleanup(instance))
        # FIXME: What does this comment mean?
        # TODO(termie): short-circuit me for tests
        # WE'LL save this for when we do shutdown,
        # instead of destroy - but destroy returns immediately
        timer = task.LoopingCall(f=None)

        def _wait_for_shutdown():
            try:
                state = self.get_info(instance['name'])['state']
                db.instance_set_state(context.get_admin_context(),
                                      instance['id'], state)
                if state == power_state.SHUTDOWN:
                    timer.stop()
                    d.callback(None)
            except Exception:
                db.instance_set_state(context.get_admin_context(),
                                      instance['id'],
                                      power_state.SHUTDOWN)
                timer.stop()
                d.callback(None)

        timer.f = _wait_for_shutdown
        timer.start(interval=0.5, now=True)
        return d

    def _cleanup(self, instance):
        target = os.path.join(FLAGS.instances_path, instance['name'])
        logging.info('instance %s: deleting instance files %s',
            instance['name'], target)
        if os.path.exists(target):
            shutil.rmtree(target)

    @defer.inlineCallbacks
    @exception.wrap_exception
    def attach_volume(self, instance_name, device_path, mountpoint):
        virt_dom = self._conn.lookupByName(instance_name)
        mount_device = mountpoint.rpartition("/")[2]
        xml = """<disk type='block'>
                     <driver name='qemu' type='raw'/>
                     <source dev='%s'/>
                     <target dev='%s' bus='virtio'/>
                 </disk>""" % (device_path, mount_device)
        virt_dom.attachDevice(xml)
        yield

    def _get_disk_xml(self, xml, device):
        """Returns the xml for the disk mounted at device"""
        try:
            doc = libxml2.parseDoc(xml)
        except:
            return None
        ctx = doc.xpathNewContext()
        try:
            ret = ctx.xpathEval('/domain/devices/disk')
            for node in ret:
                for child in node.children:
                    if child.name == 'target':
                        if child.prop('dev') == device:
                            return str(node)
        finally:
            if ctx != None:
                ctx.xpathFreeContext()
            if doc != None:
                doc.freeDoc()

    @defer.inlineCallbacks
    @exception.wrap_exception
    def detach_volume(self, instance_name, mountpoint):
        virt_dom = self._conn.lookupByName(instance_name)
        mount_device = mountpoint.rpartition("/")[2]
        xml = self._get_disk_xml(virt_dom.XMLDesc(0), mount_device)
        if not xml:
            raise exception.NotFound("No disk at %s" % mount_device)
        virt_dom.detachDevice(xml)
        yield

    @defer.inlineCallbacks
    @exception.wrap_exception
    def reboot(self, instance):
        yield self.destroy(instance, False)
        xml = self.to_xml(instance)
        yield self._conn.createXML(xml, 0)

        d = defer.Deferred()
        timer = task.LoopingCall(f=None)

        def _wait_for_reboot():
            try:
                state = self.get_info(instance['name'])['state']
                db.instance_set_state(context.get_admin_context(),
                                      instance['id'], state)
                if state == power_state.RUNNING:
                    logging.debug('instance %s: rebooted', instance['name'])
                    timer.stop()
                    d.callback(None)
            except Exception, exn:
                logging.error('_wait_for_reboot failed: %s', exn)
                db.instance_set_state(context.get_admin_context(),
                                      instance['id'],
                                      power_state.SHUTDOWN)
                timer.stop()
                d.callback(None)

        timer.f = _wait_for_reboot
        timer.start(interval=0.5, now=True)
        yield d

    @defer.inlineCallbacks
    @exception.wrap_exception
    def rescue(self, instance):
        yield self.destroy(instance, False)

        xml = self.to_xml(instance, rescue=True)
        rescue_images = {'image_id': FLAGS.rescue_image_id,
                         'kernel_id': FLAGS.rescue_kernel_id,
                         'ramdisk_id': FLAGS.rescue_ramdisk_id}
        yield self._create_image(instance, xml, 'rescue-', rescue_images)
        yield self._conn.createXML(xml, 0)

        d = defer.Deferred()
        timer = task.LoopingCall(f=None)

        def _wait_for_rescue():
            try:
                state = self.get_info(instance['name'])['state']
                db.instance_set_state(None, instance['id'], state)
                if state == power_state.RUNNING:
                    logging.debug('instance %s: rescued', instance['name'])
                    timer.stop()
                    d.callback(None)
            except Exception, exn:
                logging.error('_wait_for_rescue failed: %s', exn)
                db.instance_set_state(None,
                                      instance['id'],
                                      power_state.SHUTDOWN)
                timer.stop()
                d.callback(None)

        timer.f = _wait_for_rescue
        timer.start(interval=0.5, now=True)
        yield d

    @defer.inlineCallbacks
    @exception.wrap_exception
    def unrescue(self, instance):
        # NOTE(vish): Because reboot destroys and recreates an instance using
        #             the normal xml file, we can just call reboot here
        yield self.reboot(instance)

    @defer.inlineCallbacks
    @exception.wrap_exception
    def spawn(self, instance):
        xml = self.to_xml(instance)
        db.instance_set_state(context.get_admin_context(),
                              instance['id'],
                              power_state.NOSTATE,
                              'launching')

        yield self.nwfilter.setup_basic_filtering(instance)
        yield self.firewall_driver.prepare_instance_filter(instance)
        yield self._create_image(instance, xml)
        yield self._conn.createXML(xml, 0)
        logging.debug("instance %s: is running", instance['name'])
        yield self.firewall_driver.apply_instance_filter(instance)

        local_d = defer.Deferred()
        timer = task.LoopingCall(f=None)

        def _wait_for_boot():
            try:
                state = self.get_info(instance['name'])['state']
                db.instance_set_state(context.get_admin_context(),
                                      instance['id'], state)
                if state == power_state.RUNNING:
                    logging.debug('instance %s: booted', instance['name'])
                    timer.stop()
                    local_d.callback(None)
            except:
                logging.exception('instance %s: failed to boot',
                                  instance['name'])
                db.instance_set_state(context.get_admin_context(),
                                      instance['id'],
                                      power_state.SHUTDOWN)
                timer.stop()
                local_d.callback(None)
        timer.f = _wait_for_boot
        timer.start(interval=0.5, now=True)
        yield local_d

    def _flush_xen_console(self, virsh_output):
        logging.info('virsh said: %r' % (virsh_output,))
        virsh_output = virsh_output[0].strip()

        if virsh_output.startswith('/dev/'):
            logging.info('cool, it\'s a device')
            d = process.simple_execute("sudo dd if=%s iflag=nonblock" %
                                       virsh_output, check_exit_code=False)
            d.addCallback(lambda r: r[0])
            return d
        else:
            return ''

    def _append_to_file(self, data, fpath):
        logging.info('data: %r, fpath: %r' % (data, fpath))
        fp = open(fpath, 'a+')
        fp.write(data)
        return fpath

    def _dump_file(self, fpath):
        fp = open(fpath, 'r+')
        contents = fp.read()
        logging.info('Contents: %r' % (contents,))
        return contents

    @exception.wrap_exception
    def get_console_output(self, instance):
        console_log = os.path.join(FLAGS.instances_path, instance['name'],
                                   'console.log')
        d = process.simple_execute('sudo chown %d %s' % (os.getuid(),
                                   console_log))
        if FLAGS.libvirt_type == 'xen':
            # Xen is spethial
            d.addCallback(lambda _:
                process.simple_execute("virsh ttyconsole %s" %
                                       instance['name']))
            d.addCallback(self._flush_xen_console)
            d.addCallback(self._append_to_file, console_log)
        else:
            d.addCallback(lambda _: defer.succeed(console_log))
        d.addCallback(self._dump_file)
        return d

    @defer.inlineCallbacks
    def _create_image(self, inst, libvirt_xml, prefix='', disk_images=None):
        # syntactic nicety
        basepath = lambda fname = '', prefix = prefix: os.path.join(
                                                 FLAGS.instances_path,
                                                 inst['name'],
                                                 prefix + fname)

        # ensure directories exist and are writable
        yield process.simple_execute('mkdir -p %s' % basepath(prefix=''))
        yield process.simple_execute('chmod 0777 %s' % basepath(prefix=''))

        # TODO(termie): these are blocking calls, it would be great
        #               if they weren't.
        logging.info('instance %s: Creating image', inst['name'])
        f = open(basepath('libvirt.xml'), 'w')
        f.write(libvirt_xml)
        f.close()

        # NOTE(vish): No need add the prefix to console.log
        os.close(os.open(basepath('console.log', ''),
                         os.O_CREAT | os.O_WRONLY, 0660))

        user = manager.AuthManager().get_user(inst['user_id'])
        project = manager.AuthManager().get_project(inst['project_id'])

        if not disk_images:
            disk_images = {'image_id': inst['image_id'],
                           'kernel_id': inst['kernel_id'],
                           'ramdisk_id': inst['ramdisk_id']}
        if not os.path.exists(basepath('disk')):
            yield images.fetch(inst.image_id, basepath('disk-raw'), user,
                               project)
        if not os.path.exists(basepath('kernel')):
            yield images.fetch(inst.kernel_id, basepath('kernel'), user,
                               project)
        if not os.path.exists(basepath('ramdisk')):
            yield images.fetch(inst.ramdisk_id, basepath('ramdisk'), user,
                               project)

        execute = lambda cmd, process_input = None, check_exit_code = True: \
                  process.simple_execute(cmd=cmd,
                                         process_input=process_input,
                                         check_exit_code=check_exit_code)

        key = str(inst['key_data'])
        net = None
        network_ref = db.network_get_by_instance(context.get_admin_context(),
                                                 inst['id'])
        if network_ref['injected']:
            admin_context = context.get_admin_context()
            address = db.instance_get_fixed_address(admin_context, inst['id'])
            with open(FLAGS.injected_network_template) as f:
                net = f.read() % {'address': address,
                                  'netmask': network_ref['netmask'],
                                  'gateway': network_ref['gateway'],
                                  'broadcast': network_ref['broadcast'],
                                  'dns': network_ref['dns']}
        if key or net:
            if key:
                logging.info('instance %s: injecting key into image %s',
                    inst['name'], inst.image_id)
            if net:
                logging.info('instance %s: injecting net into image %s',
                    inst['name'], inst.image_id)
            yield disk.inject_data(basepath('disk-raw'), key, net,
                                   execute=execute)

        if os.path.exists(basepath('disk')):
            yield process.simple_execute('rm -f %s' % basepath('disk'))

        local_bytes = (instance_types.INSTANCE_TYPES[inst.instance_type]
                                                    ['local_gb']
                                                    * 1024 * 1024 * 1024)

        resize = True
        if inst['instance_type'] == 'm1.tiny' or prefix == 'rescue-':
            resize = False
        yield disk.partition(basepath('disk-raw'), basepath('disk'),
                             local_bytes, resize, execute=execute)

        if FLAGS.libvirt_type == 'uml':
            yield process.simple_execute('sudo chown root %s' %
                                         basepath('disk'))

    def to_xml(self, instance, rescue=False):
        # TODO(termie): cache?
        logging.debug('instance %s: starting toXML method', instance['name'])
        network = db.project_get_network(context.get_admin_context(),
                                         instance['project_id'])
        # FIXME(vish): stick this in db
        instance_type = instance['instance_type']
        instance_type = instance_types.INSTANCE_TYPES[instance_type]
        ip_address = db.instance_get_fixed_address(context.get_admin_context(),
                                                   instance['id'])
        # Assume that the gateway also acts as the dhcp server.
        dhcp_server = network['gateway']
        xml_info = {'type': FLAGS.libvirt_type,
                    'name': instance['name'],
                    'basepath': os.path.join(FLAGS.instances_path,
                                             instance['name']),
                    'memory_kb': instance_type['memory_mb'] * 1024,
                    'vcpus': instance_type['vcpus'],
                    'bridge_name': network['bridge'],
                    'mac_address': instance['mac_address'],
                    'ip_address': ip_address,
                    'dhcp_server': dhcp_server}
        if rescue:
            libvirt_xml = self.rescue_xml % xml_info
        else:
            libvirt_xml = self.libvirt_xml % xml_info
        logging.debug('instance %s: finished toXML method', instance['name'])

        return libvirt_xml

    def get_info(self, instance_name):
        try:
            virt_dom = self._conn.lookupByName(instance_name)
        except:
            raise exception.NotFound("Instance %s not found" % instance_name)
        (state, max_mem, mem, num_cpu, cpu_time) = virt_dom.info()
        return {'state': state,
                'max_mem': max_mem,
                'mem': mem,
                'num_cpu': num_cpu,
                'cpu_time': cpu_time}

    def get_disks(self, instance_name):
        """
        Note that this function takes an instance name, not an Instance, so
        that it can be called by monitor.

        Returns a list of all block devices for this domain.
        """
        domain = self._conn.lookupByName(instance_name)
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

    def get_interfaces(self, instance_name):
        """
        Note that this function takes an instance name, not an Instance, so
        that it can be called by monitor.

        Returns a list of all network interfaces for this instance.
        """
        domain = self._conn.lookupByName(instance_name)
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

    def block_stats(self, instance_name, disk):
        """
        Note that this function takes an instance name, not an Instance, so
        that it can be called by monitor.
        """
        domain = self._conn.lookupByName(instance_name)
        return domain.blockStats(disk)

    def interface_stats(self, instance_name, interface):
        """
        Note that this function takes an instance name, not an Instance, so
        that it can be called by monitor.
        """
        domain = self._conn.lookupByName(instance_name)
        return domain.interfaceStats(interface)

    def refresh_security_group(self, security_group_id):
        self.firewall_driver.refresh_security_group(security_group_id)


class FirewallDriver(object):
    def prepare_instance_filter(self, instance):
        """Prepare filters for the instance.

        At this point, the instance isn't running yet."""
        raise NotImplementedError()

    def apply_instance_filter(self, instance):
        """Apply instance filter.

        Once this method returns, the instance should be firewalled
        appropriately. This method should as far as possible be a
        no-op. It's vastly preferred to get everything set up in
        prepare_instance_filter.
        """
        raise NotImplementedError()

    def refresh_security_group(self, security_group_id):
        """Refresh security group from data store

        Gets called when changes have been made to the security
        group."""
        raise NotImplementedError()


class NWFilterFirewall(FirewallDriver):
    """
    This class implements a network filtering mechanism versatile
    enough for EC2 style Security Group filtering by leveraging
    libvirt's nwfilter.

    First, all instances get a filter ("nova-base-filter") applied.
    This filter provides some basic security such as protection against
    MAC spoofing, IP spoofing, and ARP spoofing.

    This filter drops all incoming ipv4 and ipv6 connections.
    Outgoing connections are never blocked.

    Second, every security group maps to a nwfilter filter(*).
    NWFilters can be updated at runtime and changes are applied
    immediately, so changes to security groups can be applied at
    runtime (as mandated by the spec).

    Security group rules are named "nova-secgroup-<id>" where <id>
    is the internal id of the security group. They're applied only on
    hosts that have instances in the security group in question.

    Updates to security groups are done by updating the data model
    (in response to API calls) followed by a request sent to all
    the nodes with instances in the security group to refresh the
    security group.

    Each instance has its own NWFilter, which references the above
    mentioned security group NWFilters. This was done because
    interfaces can only reference one filter while filters can
    reference multiple other filters. This has the added benefit of
    actually being able to add and remove security groups from an
    instance at run time. This functionality is not exposed anywhere,
    though.

    Outstanding questions:

    The name is unique, so would there be any good reason to sync
    the uuid across the nodes (by assigning it from the datamodel)?


    (*) This sentence brought to you by the redundancy department of
        redundancy.

    """

    def __init__(self, get_connection):
        self._libvirt_get_connection = get_connection
        self.static_filters_configured = False
        self.handle_security_groups = False

    def _get_connection(self):
        return self._libvirt_get_connection()
    _conn = property(_get_connection)

    def nova_dhcp_filter(self):
        """The standard allow-dhcp-server filter is an <ip> one, so it uses
           ebtables to allow traffic through. Without a corresponding rule in
           iptables, it'll get blocked anyway."""

        return '''<filter name='nova-allow-dhcp-server' chain='ipv4'>
                    <uuid>891e4787-e5c0-d59b-cbd6-41bc3c6b36fc</uuid>
                    <rule action='accept' direction='out'
                          priority='100'>
                      <udp srcipaddr='0.0.0.0'
                           dstipaddr='255.255.255.255'
                           srcportstart='68'
                           dstportstart='67'/>
                    </rule>
                    <rule action='accept' direction='in'
                          priority='100'>
                      <udp srcipaddr='$DHCPSERVER'
                           srcportstart='67'
                           dstportstart='68'/>
                    </rule>
                  </filter>'''

    def setup_basic_filtering(self, instance):
        """Set up basic filtering (MAC, IP, and ARP spoofing protection)"""
        logging.info('called setup_basic_filtering in nwfilter')

        if self.handle_security_groups:
            # No point in setting up a filter set that we'll be overriding
            # anyway.
            return

        logging.info('ensuring static filters')
        self._ensure_static_filters()

        instance_filter_name = self._instance_filter_name(instance)
        self._define_filter(self._filter_container(instance_filter_name,
                                                   ['nova-base']))

    @defer.inlineCallbacks
    def _ensure_static_filters(self):
        if self.static_filters_configured:
            return

        yield self._define_filter(self._filter_container('nova-base',
                                                   ['no-mac-spoofing',
                                                    'no-ip-spoofing',
                                                    'no-arp-spoofing',
                                                    'allow-dhcp-server']))
        yield self._define_filter(self.nova_base_ipv4_filter)
        yield self._define_filter(self.nova_base_ipv6_filter)
        yield self._define_filter(self.nova_dhcp_filter)

        self.static_filters_configured = True

    def _filter_container(self, name, filters):
        xml = '''<filter name='%s' chain='root'>%s</filter>''' % (
                 name,
                 ''.join(["<filterref filter='%s'/>" % (f,) for f in filters]))
        return xml

    def nova_base_ipv4_filter(self):
        retval = "<filter name='nova-base-ipv4' chain='ipv4'>"
        for protocol in ['tcp', 'udp', 'icmp']:
            for direction, action, priority in [('out', 'accept', 399),
                                                ('in', 'drop', 400)]:
                retval += """<rule action='%s' direction='%s' priority='%d'>
                               <%s />
                             </rule>""" % (action, direction,
                                              priority, protocol)
        retval += '</filter>'
        return retval

    def nova_base_ipv6_filter(self):
        retval = "<filter name='nova-base-ipv6' chain='ipv6'>"
        for protocol in ['tcp', 'udp', 'icmp']:
            for direction, action, priority in [('out', 'accept', 399),
                                                ('in', 'drop', 400)]:
                retval += """<rule action='%s' direction='%s' priority='%d'>
                               <%s-ipv6 />
                             </rule>""" % (action, direction,
                                             priority, protocol)
        retval += '</filter>'
        return retval

    def nova_project_filter(self, project, net, mask):
        retval = "<filter name='nova-project-%s' chain='ipv4'>" % project
        for protocol in ['tcp', 'udp', 'icmp']:
            retval += """<rule action='accept' direction='in' priority='200'>
                           <%s srcipaddr='%s' srcipmask='%s' />
                         </rule>""" % (protocol, net, mask)
        retval += '</filter>'
        return retval

    def _define_filter(self, xml):
        if callable(xml):
            xml = xml()
        d = threads.deferToThread(self._conn.nwfilterDefineXML, xml)
        return d

    @staticmethod
    def _get_net_and_mask(cidr):
        net = IPy.IP(cidr)
        return str(net.net()), str(net.netmask())


    @defer.inlineCallbacks
    def prepare_instance_filter(self, instance):
        """
        Creates an NWFilter for the given instance. In the process,
        it makes sure the filters for the security groups as well as
        the base filter are all in place.
        """

        yield self._ensure_static_filters()

        instance_filter_name = self._instance_filter_name(instance)
        instance_secgroup_filter_name = '%s-secgroup' % (instance_filter_name,)
        instance_filter_children = ['nova-base', instance_secgroup_filter_name]
        instance_secgroup_filter_children = ['nova-base-ipv4', 'nova-base-ipv6',
                                            'nova-allow-dhcp-server']

        if FLAGS.allow_project_net_traffic:
            network_ref = db.project_get_network(context.get_admin_context(),
                                                 instance['project_id'])
            net, mask = self._get_net_and_mask(network_ref['cidr'])

            project_filter = self.nova_project_filter(instance['project_id'],
                                                      net, mask)
            yield self._define_filter(project_filter)

            instance_secgroup_filter_children += [('nova-project-%s' %
                                                        instance['project_id'])]

        for security_group in db.security_group_get_by_instance(instance['id']):
            yield self.refresh_security_group(security_group['id'])

            instance_secgroup_filter_children += [('nova-secgroup-%s' %
                                                          security_group['id'])]

        yield self._define_filter(
                    self._filter_container(instance_secgroup_filter_name,
                                           instance_secgroup_filter_children))

        yield self._define_filter(
                    self._filter_container(instance_filter_name,
                                           instance_filter_children))

        return

    def refresh_security_group(self, security_group_id):
        return self._define_filter(
                   self.security_group_to_nwfilter_xml(security_group_id))

    def security_group_to_nwfilter_xml(self, security_group_id):
        security_group = db.security_group_get(context.get_admin_context(),
                                               security_group_id)
        rule_xml = ""
        for rule in security_group.rules:
            rule_xml += "<rule action='accept' direction='in' priority='300'>"
            if rule.cidr:
                net, mask = self._get_net_and_mask(rule.cidr)
                rule_xml += "<%s srcipaddr='%s' srcipmask='%s' " % \
                            (rule.protocol, net, mask)
                if rule.protocol in ['tcp', 'udp']:
                    rule_xml += "dstportstart='%s' dstportend='%s' " % \
                                (rule.from_port, rule.to_port)
                elif rule.protocol == 'icmp':
                    logging.info('rule.protocol: %r, rule.from_port: %r, '
                                 'rule.to_port: %r' %
                                 (rule.protocol, rule.from_port, rule.to_port))
                    if rule.from_port != -1:
                        rule_xml += "type='%s' " % rule.from_port
                    if rule.to_port != -1:
                        rule_xml += "code='%s' " % rule.to_port

                rule_xml += '/>\n'
            rule_xml += "</rule>\n"
        xml = "<filter name='nova-secgroup-%s' chain='ipv4'>%s</filter>" % \
              (security_group_id, rule_xml,)
        return xml

    def _instance_filter_name(self, instance):
        return 'nova-instance-%s' % instance['name']


class IptablesFirewallDriver(FirewallDriver):
    def __init__(self, execute=None):
        self.execute = execute or utils.execute
        self.instances = set()

    def apply_instance_filter(self, instance):
        """No-op. Everything is done in prepare_instance_filter"""
        pass

    def remove_instance(self, instance):
        self.instances.remove(instance)

    def add_instance(self, instance):
        self.instances.add(instance)

    def prepare_instance_filter(self, instance):
        self.add_instance(instance)
        self.apply_ruleset()

    def apply_ruleset(self):
        current_filter, _ = self.execute('sudo iptables-save -t filter')
        current_lines = current_filter.split('\n')
        new_filter = self.modify_rules(current_lines)
        self.execute('sudo iptables-restore',
                     process_input='\n'.join(new_filter))

    def modify_rules(self, current_lines):
        ctxt = context.get_admin_context()
        # Remove any trace of nova rules.
        new_filter = filter(lambda l: 'nova-' not in l, current_lines)

        seen_chains = False
        for rules_index in range(len(new_filter)):
            if not seen_chains:
                if new_filter[rules_index].startswith(':'):
                    seen_chains = True
            elif seen_chains == 1:
                if not new_filter[rules_index].startswith(':'):
                    break


        our_chains = [':nova-ipv4-fallback - [0:0]']
        our_rules  = ['-A nova-ipv4-fallback -j DROP']

        our_chains += [':nova-local - [0:0]']
        our_rules  += ['-A FORWARD -j nova-local']

        security_groups = set()
        # Add our chains
        # First, we add instance chains and rules
        for instance in self.instances:
            chain_name = self._instance_chain_name(instance)
            ip_address = self._ip_for_instance(instance)

            our_chains += [':%s - [0:0]' % chain_name]

            # Jump to the per-instance chain
            our_rules += ['-A nova-local -d %s -j %s' % (ip_address,
                                                         chain_name)]

            # Always drop invalid packets
            our_rules += ['-A %s -m state --state '
                          'INVALID -j DROP' % (chain_name,)]

            # Allow established connections
            our_rules += ['-A %s -m state --state '
                          'ESTABLISHED,RELATED -j ACCEPT' % (chain_name,)]

            # Jump to each security group chain in turn
            for security_group in \
                            db.security_group_get_by_instance(ctxt,
                                                              instance['id']):
                security_groups.add(security_group)

                sg_chain_name = self._security_group_chain_name(security_group)

                our_rules += ['-A %s -j %s' % (chain_name, sg_chain_name)]

            # Allow DHCP responses
            dhcp_server = self._dhcp_server_for_instance(instance)
            our_rules += ['-A %s -s %s -p udp --sport 67 --dport 68' % (chain_name, dhcp_server)]

            # If nothing matches, jump to the fallback chain
            our_rules += ['-A %s -j nova-ipv4-fallback' % (chain_name,)]


        # then, security group chains and rules
        for security_group in security_groups:
            chain_name = self._security_group_chain_name(security_group)
            our_chains += [':%s - [0:0]' % chain_name]

            rules = \
              db.security_group_rule_get_by_security_group(ctxt,
                                                           security_group['id'])

            for rule in rules:
                logging.info('%r', rule)
                args = ['-A', chain_name, '-p', rule.protocol]

                if rule.cidr:
                    args += ['-s', rule.cidr]
                else:
                    # Something about ipsets
                    pass

                if rule.protocol in ['udp', 'tcp']:
                    if rule.from_port == rule.to_port:
                        args += ['--dport', '%s' % (rule.from_port,)]
                    else:
                        args += ['-m', 'multiport',
                                 '--dports', '%s:%s' % (rule.from_port,
                                                        rule.to_port)]
                elif rule.protocol == 'icmp':
                    icmp_type = rule.from_port
                    icmp_code = rule.to_port

                    if icmp_type == '-1':
                        icmp_type_arg = None
                    else:
                        icmp_type_arg = '%s' % icmp_type
                        if not icmp_code == '-1':
                            icmp_type_arg += '/%s' % icmp_code

                    if icmp_type_arg:
                        args += ['-m', 'icmp', '--icmp_type', icmp_type_arg]

                args += ['-j ACCEPT']
                our_rules += [' '.join(args)]

        new_filter[rules_index:rules_index] = our_rules
        new_filter[rules_index:rules_index] = our_chains
        logging.info('new_filter: %s', '\n'.join(new_filter))
        return new_filter

    def refresh_security_group(self, security_group):
        self.apply_ruleset()

    def _security_group_chain_name(self, security_group):
        return 'nova-sg-%s' % (security_group['id'],)

    def _instance_chain_name(self, instance):
        return 'nova-inst-%s' % (instance['id'],)

    def _ip_for_instance(self, instance):
        return db.instance_get_fixed_address(context.get_admin_context(),
                                             instance['id'])

    def _dhcp_server_for_instance(self, instance):
        network = db.project_get_network(context.get_admin_context(),
                                         instance['project_id'])
        return network['gateway']
