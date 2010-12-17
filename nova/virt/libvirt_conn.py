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
:libvirt_xml_template:  Libvirt XML Template.
:rescue_image_id:  Rescue ami image (default: ami-rescue).
:rescue_kernel_id:  Rescue aki image (default: aki-rescue).
:rescue_ramdisk_id:  Rescue ari image (default: ari-rescue).
:injected_network_template:  Template file for injected network
:allow_project_net_traffic:  Whether to allow in project network traffic

"""

import logging
import os
import shutil

from eventlet import event
from eventlet import tpool

import IPy

from nova import context
from nova import db
from nova import exception
from nova import flags
from nova import utils
#from nova.api import context
from nova.auth import manager
from nova.compute import disk
from nova.compute import instance_types
from nova.compute import power_state
from nova.virt import images

from Cheetah.Template import Template

libvirt = None
libxml2 = None


FLAGS = flags.FLAGS
# TODO(vish): These flags should probably go into a shared location
flags.DEFINE_string('rescue_image_id', 'ami-rescue', 'Rescue ami image')
flags.DEFINE_string('rescue_kernel_id', 'aki-rescue', 'Rescue aki image')
flags.DEFINE_string('rescue_ramdisk_id', 'ari-rescue', 'Rescue ari image')
flags.DEFINE_string('libvirt_xml_template',
                    utils.abspath('virt/libvirt.xml.template'),
                    'Libvirt XML Template')
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
        self.libvirt_uri = self.get_uri()

        self.libvirt_xml = open(FLAGS.libvirt_xml_template).read()
        self._wrapped_conn = None
        self.read_only = read_only

    @property
    def _conn(self):
        if not self._wrapped_conn or not self._test_connection():
            logging.debug('Connecting to libvirt: %s' % self.libvirt_uri)
            self._wrapped_conn = self._connect(self.libvirt_uri,
                                               self.read_only)
        return self._wrapped_conn

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

    def get_uri(self):
        if FLAGS.libvirt_type == 'uml':
            uri = FLAGS.libvirt_uri or 'uml:///system'
        elif FLAGS.libvirt_type == 'xen':
            uri = FLAGS.libvirt_uri or 'xen:///'
        else:
            uri = FLAGS.libvirt_uri or 'qemu:///system'
        return uri

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

        done = event.Event()

        # We'll save this for when we do shutdown,
        # instead of destroy - but destroy returns immediately
        timer = utils.LoopingCall(f=None)

        def _wait_for_shutdown():
            try:
                state = self.get_info(instance['name'])['state']
                db.instance_set_state(context.get_admin_context(),
                                      instance['id'], state)
                if state == power_state.SHUTDOWN:
                    timer.stop()
            except Exception:
                db.instance_set_state(context.get_admin_context(),
                                      instance['id'],
                                      power_state.SHUTDOWN)
                timer.stop()

        timer.f = _wait_for_shutdown
        timer_done = timer.start(interval=0.5, now=True)

        # NOTE(termie): this is strictly superfluous (we could put the
        #               cleanup code in the timer), but this emulates the
        #               previous model so I am keeping it around until
        #               everything has been vetted a bit
        def _wait_for_timer():
            timer_done.wait()
            self._cleanup(instance)
            done.send()

        greenthread.spawn(_wait_for_timer)
        return done

    def _cleanup(self, instance):
        target = os.path.join(FLAGS.instances_path, instance['name'])
        logging.info('instance %s: deleting instance files %s',
            instance['name'], target)
        if os.path.exists(target):
            shutil.rmtree(target)

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

    @exception.wrap_exception
    def detach_volume(self, instance_name, mountpoint):
        virt_dom = self._conn.lookupByName(instance_name)
        mount_device = mountpoint.rpartition("/")[2]
        xml = self._get_disk_xml(virt_dom.XMLDesc(0), mount_device)
        if not xml:
            raise exception.NotFound("No disk at %s" % mount_device)
        virt_dom.detachDevice(xml)

    @exception.wrap_exception
    def reboot(self, instance):
        self.destroy(instance, False)
        xml = self.to_xml(instance)
        self._conn.createXML(xml, 0)
        timer = utils.LoopingCall(f=None)

        def _wait_for_reboot():
            try:
                state = self.get_info(instance['name'])['state']
                db.instance_set_state(context.get_admin_context(),
                                      instance['id'], state)
                if state == power_state.RUNNING:
                    logging.debug('instance %s: rebooted', instance['name'])
                    timer.stop()
            except Exception, exn:
                logging.error('_wait_for_reboot failed: %s', exn)
                db.instance_set_state(context.get_admin_context(),
                                      instance['id'],
                                      power_state.SHUTDOWN)
                timer.stop()

        timer.f = _wait_for_reboot
        return timer.start(interval=0.5, now=True)

    @exception.wrap_exception
    def rescue(self, instance):
        self.destroy(instance, False)

        xml = self.to_xml(instance, rescue=True)
        rescue_images = {'image_id': FLAGS.rescue_image_id,
                         'kernel_id': FLAGS.rescue_kernel_id,
                         'ramdisk_id': FLAGS.rescue_ramdisk_id}
        self._create_image(instance, xml, 'rescue-', rescue_images)
        self._conn.createXML(xml, 0)

        timer = utils.LoopingCall(f=None)

        def _wait_for_rescue():
            try:
                state = self.get_info(instance['name'])['state']
                db.instance_set_state(None, instance['id'], state)
                if state == power_state.RUNNING:
                    logging.debug('instance %s: rescued', instance['name'])
                    timer.stop()
            except Exception, exn:
                logging.error('_wait_for_rescue failed: %s', exn)
                db.instance_set_state(None,
                                      instance['id'],
                                      power_state.SHUTDOWN)
                timer.stop()

        timer.f = _wait_for_rescue
        return timer.start(interval=0.5, now=True)

    @exception.wrap_exception
    def unrescue(self, instance):
        # NOTE(vish): Because reboot destroys and recreates an instance using
        #             the normal xml file, we can just call reboot here
        self.reboot(instance)

    @exception.wrap_exception
    def spawn(self, instance):
        xml = self.to_xml(instance)
        db.instance_set_state(context.get_admin_context(),
                              instance['id'],
                              power_state.NOSTATE,
                              'launching')
        NWFilterFirewall(self._conn).setup_nwfilters_for_instance(instance)
        self._create_image(instance, xml)
        self._conn.createXML(xml, 0)
        logging.debug("instance %s: is running", instance['name'])

        timer = utils.LoopingCall(f=None)

        def _wait_for_boot():
            try:
                state = self.get_info(instance['name'])['state']
                db.instance_set_state(context.get_admin_context(),
                                      instance['id'], state)
                if state == power_state.RUNNING:
                    logging.debug('instance %s: booted', instance['name'])
                    timer.stop()
            except:
                logging.exception('instance %s: failed to boot',
                                  instance['name'])
                db.instance_set_state(context.get_admin_context(),
                                      instance['id'],
                                      power_state.SHUTDOWN)
                timer.stop()

        timer.f = _wait_for_boot
        return timer.start(interval=0.5, now=True)

    def _flush_xen_console(self, virsh_output):
        logging.info('virsh said: %r' % (virsh_output,))
        virsh_output = virsh_output[0].strip()

        if virsh_output.startswith('/dev/'):
            logging.info('cool, it\'s a device')
            out, err = utils.execute("sudo dd if=%s iflag=nonblock" %
                                     virsh_output, check_exit_code=False)
            return out
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

        utils.execute('sudo chown %d %s' % (os.getuid(), console_log))

        if FLAGS.libvirt_type == 'xen':
            # Xen is special
            virsh_output = utils.execute("virsh ttyconsole %s" %
                                         instance['name'])
            data = self._flush_xen_console(virsh_output)
            fpath = self._append_to_file(data, console_log)
        else:
            fpath = console_log

        return self._dump_file(fpath)

    def _create_image(self, inst, libvirt_xml, prefix='', disk_images=None):
        # syntactic nicety
        basepath = lambda fname = '', prefix = prefix: os.path.join(
                                                 FLAGS.instances_path,
                                                 inst['name'],
                                                 prefix + fname)

        # ensure directories exist and are writable
        utils.execute('mkdir -p %s' % basepath(prefix=''))
        utils.execute('chmod 0777 %s' % basepath(prefix=''))

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
            images.fetch(inst.image_id, basepath('disk-raw'), user,
                         project)

        if inst['kernel_id']:
            if not os.path.exists(basepath('kernel')):
                images.fetch(inst['kernel_id'], basepath('kernel'),
                             user, project)
            if inst['ramdisk_id']:
                if not os.path.exists(basepath('ramdisk')):
                    images.fetch(inst['ramdisk_id'], basepath('ramdisk'),
                                 user, project)

        def execute(cmd, process_input=None, check_exit_code=True):
            return utils.execute(cmd=cmd,
                                 process_input=process_input,
                                 check_exit_code=check_exit_code)

        # For now, we assume that if we're not using a kernel, we're using a
        # partitioned disk image where the target partition is the first
        # partition
        target_partition = None
        if not inst['kernel_id']:
            target_partition = "1"

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
            try:
                disk.inject_data(basepath('disk-raw'), key, net,
                                 partition=target_partition,
                                 execute=execute)
            except Exception as e:
                # This could be a windows image, or a vmdk format disk
                logging.warn('instance %s: ignoring error injecting data'
                             ' into image %s (%s)',
                             inst['name'], inst.image_id, e)

        if inst['kernel_id']:
            if os.path.exists(basepath('disk')):
                utils.execute('rm -f %s' % basepath('disk'))

        local_bytes = (instance_types.INSTANCE_TYPES[inst.instance_type]
                                                    ['local_gb']
                                                    * 1024 * 1024 * 1024)

        resize = True
        if inst['instance_type'] == 'm1.tiny' or prefix == 'rescue-':
            resize = False

        if inst['kernel_id']:
            disk.partition(basepath('disk-raw'), basepath('disk'),
                           local_bytes, resize, execute=execute)
        else:
            os.rename(basepath('disk-raw'), basepath('disk'))
            disk.extend(basepath('disk'), local_bytes, execute=execute)

        if FLAGS.libvirt_type == 'uml':
            utils.execute('sudo chown root %s' % basepath('disk'))

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
                    'dhcp_server': dhcp_server,
                    'rescue': rescue}
        if not rescue:
            if instance['kernel_id']:
                xml_info['kernel'] = xml_info['basepath'] + "/kernel"

            if instance['ramdisk_id']:
                xml_info['ramdisk'] = xml_info['basepath'] + "/ramdisk"

            xml_info['disk'] = xml_info['basepath'] + "/disk"

        xml = str(Template(self.libvirt_xml, searchList=[xml_info]))
        logging.debug('instance %s: finished toXML method', instance['name'])

        return xml

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
        fw = NWFilterFirewall(self._conn)
        fw.ensure_security_group_filter(security_group_id)


class NWFilterFirewall(object):
    """
    This class implements a network filtering mechanism versatile
    enough for EC2 style Security Group filtering by leveraging
    libvirt's nwfilter.

    First, all instances get a filter ("nova-base-filter") applied.
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
        self._conn = get_connection

    nova_base_filter = '''<filter name='nova-base' chain='root'>
                            <uuid>26717364-50cf-42d1-8185-29bf893ab110</uuid>
                            <filterref filter='no-mac-spoofing'/>
                            <filterref filter='no-ip-spoofing'/>
                            <filterref filter='no-arp-spoofing'/>
                            <filterref filter='allow-dhcp-server'/>
                            <filterref filter='nova-allow-dhcp-server'/>
                            <filterref filter='nova-base-ipv4'/>
                            <filterref filter='nova-base-ipv6'/>
                          </filter>'''

    nova_dhcp_filter = '''<filter name='nova-allow-dhcp-server' chain='ipv4'>
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

    def nova_base_ipv4_filter(self):
        retval = "<filter name='nova-base-ipv4' chain='ipv4'>"
        for protocol in ['tcp', 'udp', 'icmp']:
            for direction, action, priority in [('out', 'accept', 399),
                                                ('inout', 'drop', 400)]:
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
                                                ('inout', 'drop', 400)]:
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

        # execute in a native thread and block current greenthread until done
        tpool.execute(self._conn.nwfilterDefineXML, xml)

    @staticmethod
    def _get_net_and_mask(cidr):
        net = IPy.IP(cidr)
        return str(net.net()), str(net.netmask())

    def setup_nwfilters_for_instance(self, instance):
        """
        Creates an NWFilter for the given instance. In the process,
        it makes sure the filters for the security groups as well as
        the base filter are all in place.
        """

        self._define_filter(self.nova_base_ipv4_filter)
        self._define_filter(self.nova_base_ipv6_filter)
        self._define_filter(self.nova_dhcp_filter)
        self._define_filter(self.nova_base_filter)

        nwfilter_xml = "<filter name='nova-instance-%s' chain='root'>\n" \
                       "  <filterref filter='nova-base' />\n" % \
                       instance['name']

        if FLAGS.allow_project_net_traffic:
            network_ref = db.project_get_network(context.get_admin_context(),
                                                 instance['project_id'])
            net, mask = self._get_net_and_mask(network_ref['cidr'])
            project_filter = self.nova_project_filter(instance['project_id'],
                                                      net, mask)
            self._define_filter(project_filter)

            nwfilter_xml += "  <filterref filter='nova-project-%s' />\n" % \
                            instance['project_id']

        for security_group in instance.security_groups:
            self.ensure_security_group_filter(security_group['id'])

            nwfilter_xml += "  <filterref filter='nova-secgroup-%d' />\n" % \
                            security_group['id']
        nwfilter_xml += "</filter>"

        self._define_filter(nwfilter_xml)

    def ensure_security_group_filter(self, security_group_id):
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
