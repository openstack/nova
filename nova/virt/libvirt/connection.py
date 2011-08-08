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

Supports KVM, LXC, QEMU, UML, and XEN.

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

import hashlib
import multiprocessing
import netaddr
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from xml.dom import minidom
from xml.etree import ElementTree

from eventlet import greenthread
from eventlet import tpool

from nova import context as nova_context
from nova import db
from nova import exception
from nova import flags
import nova.image
from nova import log as logging
from nova import utils
from nova import vnc
from nova.auth import manager
from nova.compute import instance_types
from nova.compute import power_state
from nova.virt import disk
from nova.virt import driver
from nova.virt import images
from nova.virt.libvirt import netutils


libvirt = None
libxml2 = None
Template = None


LOG = logging.getLogger('nova.virt.libvirt_conn')


FLAGS = flags.FLAGS
flags.DECLARE('live_migration_retry_count', 'nova.compute.manager')
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
                    'kvm, lxc, qemu, uml, xen)')
flags.DEFINE_string('libvirt_uri',
                    '',
                    'Override the default libvirt URI (which is dependent'
                    ' on libvirt_type)')
flags.DEFINE_bool('allow_project_net_traffic',
                  True,
                  'Whether to allow in project network traffic')
flags.DEFINE_bool('use_cow_images',
                  True,
                  'Whether to use cow images')
flags.DEFINE_string('ajaxterm_portrange',
                    '10000-12000',
                    'Range of ports that ajaxterm should randomly try to bind')
flags.DEFINE_string('firewall_driver',
                    'nova.virt.libvirt.firewall.IptablesFirewallDriver',
                    'Firewall driver (defaults to iptables)')
flags.DEFINE_string('cpuinfo_xml_template',
                    utils.abspath('virt/cpuinfo.xml.template'),
                    'CpuInfo XML Template (Used only live migration now)')
flags.DEFINE_string('live_migration_uri',
                    "qemu+tcp://%s/system",
                    'Define protocol used by live_migration feature')
flags.DEFINE_string('live_migration_flag',
                    "VIR_MIGRATE_UNDEFINE_SOURCE, VIR_MIGRATE_PEER2PEER",
                    'Define live migration behavior.')
flags.DEFINE_integer('live_migration_bandwidth', 0,
                    'Define live migration behavior')
flags.DEFINE_string('qemu_img', 'qemu-img',
                    'binary to use for qemu-img commands')
flags.DEFINE_string('libvirt_vif_type', 'bridge',
                    'Type of VIF to create.')
flags.DEFINE_string('libvirt_vif_driver',
                    'nova.virt.libvirt.vif.LibvirtBridgeDriver',
                    'The libvirt VIF driver to configure the VIFs.')


def get_connection(read_only):
    # These are loaded late so that there's no need to install these
    # libraries when not using libvirt.
    # Cheetah is separate because the unit tests want to load Cheetah,
    # but not libvirt.
    global libvirt
    global libxml2
    if libvirt is None:
        libvirt = __import__('libvirt')
    if libxml2 is None:
        libxml2 = __import__('libxml2')
    _late_load_cheetah()
    return LibvirtConnection(read_only)


def _late_load_cheetah():
    global Template
    if Template is None:
        t = __import__('Cheetah.Template', globals(), locals(),
                       ['Template'], -1)
        Template = t.Template


def _strip_dev(mount_path):
        return re.sub(r'^/dev/', '', mount_path)


class LibvirtConnection(driver.ComputeDriver):

    def __init__(self, read_only):
        super(LibvirtConnection, self).__init__()
        self.libvirt_uri = self.get_uri()

        self.libvirt_xml = open(FLAGS.libvirt_xml_template).read()
        self.cpuinfo_xml = open(FLAGS.cpuinfo_xml_template).read()
        self._wrapped_conn = None
        self.read_only = read_only

        fw_class = utils.import_class(FLAGS.firewall_driver)
        self.firewall_driver = fw_class(get_connection=self._get_connection)
        self.vif_driver = utils.import_object(FLAGS.libvirt_vif_driver)

    def init_host(self, host):
        # NOTE(nsokolov): moved instance restarting to ComputeManager
        pass

    def _get_connection(self):
        if not self._wrapped_conn or not self._test_connection():
            LOG.debug(_('Connecting to libvirt: %s'), self.libvirt_uri)
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
                LOG.debug(_('Connection to libvirt broke'))
                return False
            raise

    def get_uri(self):
        if FLAGS.libvirt_type == 'uml':
            uri = FLAGS.libvirt_uri or 'uml:///system'
        elif FLAGS.libvirt_type == 'xen':
            uri = FLAGS.libvirt_uri or 'xen:///'
        elif FLAGS.libvirt_type == 'lxc':
            uri = FLAGS.libvirt_uri or 'lxc:///'
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

    def _map_to_instance_info(self, domain):
        """Gets info from a virsh domain object into an InstanceInfo"""

        # domain.info() returns a list of:
        #    state:       one of the state values (virDomainState)
        #    maxMemory:   the maximum memory used by the domain
        #    memory:      the current amount of memory used by the domain
        #    nbVirtCPU:   the number of virtual CPU
        #    puTime:      the time used by the domain in nanoseconds

        (state, _max_mem, _mem, _num_cpu, _cpu_time) = domain.info()
        name = domain.name()

        return driver.InstanceInfo(name, state)

    def list_instances_detail(self):
        infos = []
        for domain_id in self._conn.listDomainsID():
            domain = self._conn.lookupByID(domain_id)
            info = self._map_to_instance_info(domain)
            infos.append(info)
        return infos

    def plug_vifs(self, instance, network_info):
        """Plugin VIFs into networks."""
        for (network, mapping) in network_info:
            self.vif_driver.plug(instance, network, mapping)

    def destroy(self, instance, network_info, cleanup=True):
        instance_name = instance['name']

        try:
            virt_dom = self._lookup_by_name(instance_name)
        except exception.NotFound:
            virt_dom = None

        # If the instance is already terminated, we're still happy
        # Otherwise, destroy it
        if virt_dom is not None:
            try:
                virt_dom.destroy()
            except libvirt.libvirtError as e:
                is_okay = False
                errcode = e.get_error_code()
                if errcode == libvirt.VIR_ERR_OPERATION_INVALID:
                    # If the instance if already shut off, we get this:
                    # Code=55 Error=Requested operation is not valid:
                    # domain is not running
                    (state, _max_mem, _mem, _cpus, _t) = virt_dom.info()
                    if state == power_state.SHUTOFF:
                        is_okay = True

                if not is_okay:
                    LOG.warning(_("Error from libvirt during destroy of "
                                  "%(instance_name)s. Code=%(errcode)s "
                                  "Error=%(e)s") %
                                locals())
                    raise

            try:
                # NOTE(justinsb): We remove the domain definition. We probably
                # would do better to keep it if cleanup=False (e.g. volumes?)
                # (e.g. #2 - not losing machines on failure)
                virt_dom.undefine()
            except libvirt.libvirtError as e:
                errcode = e.get_error_code()
                LOG.warning(_("Error from libvirt during undefine of "
                              "%(instance_name)s. Code=%(errcode)s "
                              "Error=%(e)s") %
                            locals())
                raise

            for (network, mapping) in network_info:
                self.vif_driver.unplug(instance, network, mapping)

        def _wait_for_destroy():
            """Called at an interval until the VM is gone."""
            instance_name = instance['name']

            try:
                state = self.get_info(instance_name)['state']
            except exception.NotFound:
                msg = _("Instance %s destroyed successfully.") % instance_name
                LOG.info(msg)
                raise utils.LoopingCallDone

        timer = utils.LoopingCall(_wait_for_destroy)
        timer.start(interval=0.5, now=True)

        self.firewall_driver.unfilter_instance(instance,
                                               network_info=network_info)

        if cleanup:
            self._cleanup(instance)

        return True

    def _cleanup(self, instance):
        target = os.path.join(FLAGS.instances_path, instance['name'])
        instance_name = instance['name']
        LOG.info(_('instance %(instance_name)s: deleting instance files'
                ' %(target)s') % locals())
        if FLAGS.libvirt_type == 'lxc':
            disk.destroy_container(target, instance, nbd=FLAGS.use_cow_images)
        if os.path.exists(target):
            shutil.rmtree(target)

    @exception.wrap_exception()
    def attach_volume(self, instance_name, device_path, mountpoint):
        virt_dom = self._lookup_by_name(instance_name)
        mount_device = mountpoint.rpartition("/")[2]
        (type, protocol, name) = \
            self._get_volume_device_info(device_path)
        if type == 'block':
            xml = """<disk type='block'>
                         <driver name='qemu' type='raw'/>
                         <source dev='%s'/>
                         <target dev='%s' bus='virtio'/>
                     </disk>""" % (device_path, mount_device)
        elif type == 'network':
            xml = """<disk type='network'>
                         <driver name='qemu' type='raw'/>
                         <source protocol='%s' name='%s'/>
                         <target dev='%s' bus='virtio'/>
                     </disk>""" % (protocol, name, mount_device)
        virt_dom.attachDevice(xml)

    def _get_disk_xml(self, xml, device):
        """Returns the xml for the disk mounted at device"""
        try:
            doc = libxml2.parseDoc(xml)
        except Exception:
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
            if ctx is not None:
                ctx.xpathFreeContext()
            if doc is not None:
                doc.freeDoc()

    @exception.wrap_exception()
    def detach_volume(self, instance_name, mountpoint):
        virt_dom = self._lookup_by_name(instance_name)
        mount_device = mountpoint.rpartition("/")[2]
        xml = self._get_disk_xml(virt_dom.XMLDesc(0), mount_device)
        if not xml:
            raise exception.DiskNotFound(location=mount_device)
        virt_dom.detachDevice(xml)

    @exception.wrap_exception()
    def snapshot(self, context, instance, image_href):
        """Create snapshot from a running VM instance.

        This command only works with qemu 0.14+, the qemu_img flag is
        provided so that a locally compiled binary of qemu-img can be used
        to support this command.

        """
        virt_dom = self._lookup_by_name(instance['name'])

        (image_service, image_id) = nova.image.get_image_service(
            instance['image_ref'])
        base = image_service.show(context, image_id)
        (snapshot_image_service, snapshot_image_id) = \
            nova.image.get_image_service(image_href)
        snapshot = snapshot_image_service.show(context, snapshot_image_id)

        metadata = {'is_public': False,
                    'status': 'active',
                    'name': snapshot['name'],
                    'properties': {
                                   'kernel_id': instance['kernel_id'],
                                   'image_location': 'snapshot',
                                   'image_state': 'available',
                                   'owner_id': instance['project_id'],
                                   'ramdisk_id': instance['ramdisk_id'],
                                   }
                    }
        if 'architecture' in base['properties']:
            arch = base['properties']['architecture']
            metadata['properties']['architecture'] = arch

        if 'disk_format' in base:
            metadata['disk_format'] = base['disk_format']

        if 'container_format' in base:
            metadata['container_format'] = base['container_format']

        # Make the snapshot
        snapshot_name = uuid.uuid4().hex
        snapshot_xml = """
        <domainsnapshot>
            <name>%s</name>
        </domainsnapshot>
        """ % snapshot_name
        snapshot_ptr = virt_dom.snapshotCreateXML(snapshot_xml, 0)

        # Find the disk
        xml_desc = virt_dom.XMLDesc(0)
        domain = ElementTree.fromstring(xml_desc)
        source = domain.find('devices/disk/source')
        disk_path = source.get('file')

        # Export the snapshot to a raw image
        temp_dir = tempfile.mkdtemp()
        out_path = os.path.join(temp_dir, snapshot_name)
        qemu_img_cmd = (FLAGS.qemu_img,
                        'convert',
                        '-f',
                        'qcow2',
                        '-O',
                        'raw',
                        '-s',
                        snapshot_name,
                        disk_path,
                        out_path)
        utils.execute(*qemu_img_cmd)

        # Upload that image to the image service
        with open(out_path) as image_file:
            image_service.update(context,
                                 image_href,
                                 metadata,
                                 image_file)

        # Clean up
        shutil.rmtree(temp_dir)

    @exception.wrap_exception()
    def reboot(self, instance, network_info):
        """Reboot a virtual machine, given an instance reference.

        This method actually destroys and re-creates the domain to ensure the
        reboot happens, as the guest OS cannot ignore this action.

        """
        virt_dom = self._conn.lookupByName(instance['name'])
        # NOTE(itoumsn): Use XML delived from the running instance
        # instead of using to_xml(instance). This is almost the ultimate
        # stupid workaround.
        xml = virt_dom.XMLDesc(0)
        # NOTE(itoumsn): self.shutdown() and wait instead of self.destroy() is
        # better because we cannot ensure flushing dirty buffers
        # in the guest OS. But, in case of KVM, shutdown() does not work...
        self.destroy(instance, network_info, cleanup=False)
        self.plug_vifs(instance, network_info)
        self.firewall_driver.setup_basic_filtering(instance)
        self.firewall_driver.prepare_instance_filter(instance)
        self._create_new_domain(xml)
        self.firewall_driver.apply_instance_filter(instance)

        def _wait_for_reboot():
            """Called at an interval until the VM is running again."""
            instance_name = instance['name']

            try:
                state = self.get_info(instance_name)['state']
            except exception.NotFound:
                msg = _("During reboot, %s disappeared.") % instance_name
                LOG.error(msg)
                raise utils.LoopingCallDone

            if state == power_state.RUNNING:
                msg = _("Instance %s rebooted successfully.") % instance_name
                LOG.info(msg)
                raise utils.LoopingCallDone

        timer = utils.LoopingCall(_wait_for_reboot)
        return timer.start(interval=0.5, now=True)

    @exception.wrap_exception()
    def pause(self, instance, callback):
        """Pause VM instance"""
        dom = self._lookup_by_name(instance.name)
        dom.suspend()

    @exception.wrap_exception()
    def unpause(self, instance, callback):
        """Unpause paused VM instance"""
        dom = self._lookup_by_name(instance.name)
        dom.resume()

    @exception.wrap_exception()
    def suspend(self, instance, callback):
        """Suspend the specified instance"""
        dom = self._lookup_by_name(instance.name)
        dom.managedSave(0)

    @exception.wrap_exception()
    def resume(self, instance, callback):
        """resume the specified instance"""
        dom = self._lookup_by_name(instance.name)
        dom.create()

    @exception.wrap_exception()
    def rescue(self, context, instance, callback, network_info):
        """Loads a VM using rescue images.

        A rescue is normally performed when something goes wrong with the
        primary images and data needs to be corrected/recovered. Rescuing
        should not edit or over-ride the original image, only allow for
        data recovery.

        """
        self.destroy(instance, network_info, cleanup=False)

        xml = self.to_xml(instance, rescue=True)
        rescue_images = {'image_id': FLAGS.rescue_image_id,
                         'kernel_id': FLAGS.rescue_kernel_id,
                         'ramdisk_id': FLAGS.rescue_ramdisk_id}
        self._create_image(context, instance, xml, '.rescue', rescue_images)
        self._create_new_domain(xml)

        def _wait_for_rescue():
            """Called at an interval until the VM is running again."""
            instance_name = instance['name']

            try:
                state = self.get_info(instance_name)['state']
            except exception.NotFound:
                msg = _("During reboot, %s disappeared.") % instance_name
                LOG.error(msg)
                raise utils.LoopingCallDone

            if state == power_state.RUNNING:
                msg = _("Instance %s rescued successfully.") % instance_name
                LOG.info(msg)
                raise utils.LoopingCallDone

        timer = utils.LoopingCall(_wait_for_rescue)
        return timer.start(interval=0.5, now=True)

    @exception.wrap_exception()
    def unrescue(self, instance, network_info):
        """Reboot the VM which is being rescued back into primary images.

        Because reboot destroys and re-creates instances, unresue should
        simply call reboot.

        """
        self.reboot(instance, network_info)

    @exception.wrap_exception()
    def poll_rescued_instances(self, timeout):
        pass

    # NOTE(ilyaalekseyev): Implementation like in multinics
    # for xenapi(tr3buchet)
    @exception.wrap_exception()
    def spawn(self, context, instance, network_info,
              block_device_mapping=None):
        xml = self.to_xml(instance, False, network_info=network_info,
                          block_device_mapping=block_device_mapping)
        block_device_mapping = block_device_mapping or []
        self.firewall_driver.setup_basic_filtering(instance, network_info)
        self.firewall_driver.prepare_instance_filter(instance, network_info)
        self._create_image(context, instance, xml, network_info=network_info,
                           block_device_mapping=block_device_mapping)
        domain = self._create_new_domain(xml)
        LOG.debug(_("instance %s: is running"), instance['name'])
        self.firewall_driver.apply_instance_filter(instance)

        def _wait_for_boot():
            """Called at an interval until the VM is running."""
            instance_name = instance['name']

            try:
                state = self.get_info(instance_name)['state']
            except exception.NotFound:
                msg = _("During reboot, %s disappeared.") % instance_name
                LOG.error(msg)
                raise utils.LoopingCallDone

            if state == power_state.RUNNING:
                msg = _("Instance %s spawned successfully.") % instance_name
                LOG.info(msg)
                raise utils.LoopingCallDone

        timer = utils.LoopingCall(_wait_for_boot)
        return timer.start(interval=0.5, now=True)

    def _flush_xen_console(self, virsh_output):
        LOG.info(_('virsh said: %r'), virsh_output)
        virsh_output = virsh_output[0].strip()

        if virsh_output.startswith('/dev/'):
            LOG.info(_("cool, it's a device"))
            out, err = utils.execute('sudo', 'dd',
                                     "if=%s" % virsh_output,
                                     'iflag=nonblock',
                                     check_exit_code=False)
            return out
        else:
            return ''

    def _append_to_file(self, data, fpath):
        LOG.info(_('data: %(data)r, fpath: %(fpath)r') % locals())
        fp = open(fpath, 'a+')
        fp.write(data)
        return fpath

    def _dump_file(self, fpath):
        fp = open(fpath, 'r+')
        contents = fp.read()
        LOG.info(_('Contents of file %(fpath)s: %(contents)r') % locals())
        return contents

    @exception.wrap_exception()
    def get_console_output(self, instance):
        console_log = os.path.join(FLAGS.instances_path, instance['name'],
                                   'console.log')

        utils.execute('sudo', 'chown', os.getuid(), console_log)

        if FLAGS.libvirt_type == 'xen':
            # Xen is special
            virsh_output = utils.execute('virsh', 'ttyconsole',
                                         instance['name'])
            data = self._flush_xen_console(virsh_output)
            fpath = self._append_to_file(data, console_log)
        elif FLAGS.libvirt_type == 'lxc':
            # LXC is also special
            LOG.info(_("Unable to read LXC console"))
        else:
            fpath = console_log

        return self._dump_file(fpath)

    @exception.wrap_exception()
    def get_ajax_console(self, instance):
        def get_open_port():
            start_port, end_port = FLAGS.ajaxterm_portrange.split("-")
            for i in xrange(0, 100):  # don't loop forever
                port = random.randint(int(start_port), int(end_port))
                # netcat will exit with 0 only if the port is in use,
                # so a nonzero return value implies it is unused
                cmd = 'netcat', '0.0.0.0', port, '-w', '1'
                try:
                    stdout, stderr = utils.execute(*cmd, process_input='')
                except exception.ProcessExecutionError:
                    return port
            raise Exception(_('Unable to find an open port'))

        def get_pty_for_instance(instance_name):
            virt_dom = self._lookup_by_name(instance_name)
            xml = virt_dom.XMLDesc(0)
            dom = minidom.parseString(xml)

            for serial in dom.getElementsByTagName('serial'):
                if serial.getAttribute('type') == 'pty':
                    source = serial.getElementsByTagName('source')[0]
                    return source.getAttribute('path')

        port = get_open_port()
        token = str(uuid.uuid4())
        host = instance['host']

        ajaxterm_cmd = 'sudo socat - %s' \
                       % get_pty_for_instance(instance['name'])

        cmd = '%s/tools/ajaxterm/ajaxterm.py --command "%s" -t %s -p %s' \
              % (utils.novadir(), ajaxterm_cmd, token, port)

        subprocess.Popen(cmd, shell=True)
        return {'token': token, 'host': host, 'port': port}

    def get_host_ip_addr(self):
        return FLAGS.my_ip

    @exception.wrap_exception()
    def get_vnc_console(self, instance):
        def get_vnc_port_for_instance(instance_name):
            virt_dom = self._lookup_by_name(instance_name)
            xml = virt_dom.XMLDesc(0)
            # TODO: use etree instead of minidom
            dom = minidom.parseString(xml)

            for graphic in dom.getElementsByTagName('graphics'):
                if graphic.getAttribute('type') == 'vnc':
                    return graphic.getAttribute('port')

        port = get_vnc_port_for_instance(instance['name'])
        token = str(uuid.uuid4())
        host = instance['host']

        return {'token': token, 'host': host, 'port': port}

    @staticmethod
    def _cache_image(fn, target, fname, cow=False, *args, **kwargs):
        """Wrapper for a method that creates an image that caches the image.

        This wrapper will save the image into a common store and create a
        copy for use by the hypervisor.

        The underlying method should specify a kwarg of target representing
        where the image will be saved.

        fname is used as the filename of the base image.  The filename needs
        to be unique to a given image.

        If cow is True, it will make a CoW image instead of a copy.
        """
        if not os.path.exists(target):
            base_dir = os.path.join(FLAGS.instances_path, '_base')
            if not os.path.exists(base_dir):
                os.mkdir(base_dir)
            base = os.path.join(base_dir, fname)

            @utils.synchronized(fname)
            def call_if_not_exists(base, fn, *args, **kwargs):
                if not os.path.exists(base):
                    fn(target=base, *args, **kwargs)

            call_if_not_exists(base, fn, *args, **kwargs)

            if cow:
                utils.execute('qemu-img', 'create', '-f', 'qcow2', '-o',
                              'cluster_size=2M,backing_file=%s' % base,
                              target)
            else:
                utils.execute('cp', base, target)

    def _fetch_image(self, context, target, image_id, user_id, project_id,
                     size=None):
        """Grab image and optionally attempt to resize it"""
        images.fetch(context, image_id, target, user_id, project_id)
        if size:
            disk.extend(target, size)

    def _create_local(self, target, local_gb):
        """Create a blank image of specified size"""
        utils.execute('truncate', target, '-s', "%dG" % local_gb)
        # TODO(vish): should we format disk by default?

    def _create_image(self, context, inst, libvirt_xml, suffix='',
                      disk_images=None, network_info=None,
                      block_device_mapping=None):
        block_device_mapping = block_device_mapping or []

        if not suffix:
            suffix = ''

        # syntactic nicety
        def basepath(fname='', suffix=suffix):
            return os.path.join(FLAGS.instances_path,
                                inst['name'],
                                fname + suffix)

        # ensure directories exist and are writable
        utils.execute('mkdir', '-p', basepath(suffix=''))

        LOG.info(_('instance %s: Creating image'), inst['name'])
        f = open(basepath('libvirt.xml'), 'w')
        f.write(libvirt_xml)
        f.close()

        if FLAGS.libvirt_type == 'lxc':
            container_dir = '%s/rootfs' % basepath(suffix='')
            utils.execute('mkdir', '-p', container_dir)

        # NOTE(vish): No need add the suffix to console.log
        os.close(os.open(basepath('console.log', ''),
                         os.O_CREAT | os.O_WRONLY, 0660))

        if not disk_images:
            disk_images = {'image_id': inst['image_ref'],
                           'kernel_id': inst['kernel_id'],
                           'ramdisk_id': inst['ramdisk_id']}

        if disk_images['kernel_id']:
            fname = '%08x' % int(disk_images['kernel_id'])
            self._cache_image(fn=self._fetch_image,
                              context=context,
                              target=basepath('kernel'),
                              fname=fname,
                              image_id=disk_images['kernel_id'],
                              user_id=inst['user_id'],
                              project_id=inst['project_id'])
            if disk_images['ramdisk_id']:
                fname = '%08x' % int(disk_images['ramdisk_id'])
                self._cache_image(fn=self._fetch_image,
                                  context=context,
                                  target=basepath('ramdisk'),
                                  fname=fname,
                                  image_id=disk_images['ramdisk_id'],
                                  user_id=inst['user_id'],
                                  project_id=inst['project_id'])

        root_fname = hashlib.sha1(disk_images['image_id']).hexdigest()
        size = FLAGS.minimum_root_size

        inst_type_id = inst['instance_type_id']
        inst_type = instance_types.get_instance_type(inst_type_id)
        if inst_type['name'] == 'm1.tiny' or suffix == '.rescue':
            size = None
            root_fname += "_sm"

        if not self._volume_in_mapping(self.root_mount_device,
                                       block_device_mapping):
            self._cache_image(fn=self._fetch_image,
                              context=context,
                              target=basepath('disk'),
                              fname=root_fname,
                              cow=FLAGS.use_cow_images,
                              image_id=disk_images['image_id'],
                              user_id=inst['user_id'],
                              project_id=inst['project_id'],
                              size=size)

        if inst_type['local_gb'] and not self._volume_in_mapping(
            self.local_mount_device, block_device_mapping):
            self._cache_image(fn=self._create_local,
                              target=basepath('disk.local'),
                              fname="local_%s" % inst_type['local_gb'],
                              cow=FLAGS.use_cow_images,
                              local_gb=inst_type['local_gb'])

        # For now, we assume that if we're not using a kernel, we're using a
        # partitioned disk image where the target partition is the first
        # partition
        target_partition = None
        if not inst['kernel_id']:
            target_partition = "1"

        if FLAGS.libvirt_type == 'lxc':
            target_partition = None

        if inst['key_data']:
            key = str(inst['key_data'])
        else:
            key = None
        net = None

        nets = []
        ifc_template = open(FLAGS.injected_network_template).read()
        ifc_num = -1
        have_injected_networks = False
        admin_context = nova_context.get_admin_context()
        for (network_ref, mapping) in network_info:
            ifc_num += 1

            if not network_ref['injected']:
                continue

            have_injected_networks = True
            address = mapping['ips'][0]['ip']
            netmask = mapping['ips'][0]['netmask']
            address_v6 = None
            gateway_v6 = None
            netmask_v6 = None
            if FLAGS.use_ipv6:
                address_v6 = mapping['ip6s'][0]['ip']
                netmask_v6 = mapping['ip6s'][0]['netmask']
                gateway_v6 = mapping['gateway6']
            net_info = {'name': 'eth%d' % ifc_num,
                   'address': address,
                   'netmask': netmask,
                   'gateway': mapping['gateway'],
                   'broadcast': mapping['broadcast'],
                   'dns': ' '.join(mapping['dns']),
                   'address_v6': address_v6,
                   'gateway6': gateway_v6,
                   'netmask_v6': netmask_v6}
            nets.append(net_info)

        if have_injected_networks:
            net = str(Template(ifc_template,
                               searchList=[{'interfaces': nets,
                                            'use_ipv6': FLAGS.use_ipv6}]))

        if key or net:
            inst_name = inst['name']
            img_id = inst.image_ref
            if key:
                LOG.info(_('instance %(inst_name)s: injecting key into'
                        ' image %(img_id)s') % locals())
            if net:
                LOG.info(_('instance %(inst_name)s: injecting net into'
                        ' image %(img_id)s') % locals())
            try:
                disk.inject_data(basepath('disk'), key, net,
                                 partition=target_partition,
                                 nbd=FLAGS.use_cow_images)

                if FLAGS.libvirt_type == 'lxc':
                    disk.setup_container(basepath('disk'),
                                        container_dir=container_dir,
                                        nbd=FLAGS.use_cow_images)
            except Exception as e:
                # This could be a windows image, or a vmdk format disk
                LOG.warn(_('instance %(inst_name)s: ignoring error injecting'
                        ' data into image %(img_id)s (%(e)s)') % locals())

        if FLAGS.libvirt_type == 'uml':
            utils.execute('sudo', 'chown', 'root', basepath('disk'))

    root_mount_device = 'vda'  # FIXME for now. it's hard coded.
    local_mount_device = 'vdb'  # FIXME for now. it's hard coded.

    def _volume_in_mapping(self, mount_device, block_device_mapping):
        mount_device_ = _strip_dev(mount_device)
        for vol in block_device_mapping:
            vol_mount_device = _strip_dev(vol['mount_device'])
            if vol_mount_device == mount_device_:
                return True
        return False

    def _get_volume_device_info(self, device_path):
        if device_path.startswith('/dev/'):
            return ('block', None, None)
        elif ':' in device_path:
            (protocol, name) = device_path.split(':')
            return ('network', protocol, name)
        else:
            raise exception.InvalidDevicePath(path=device_path)

    def _prepare_xml_info(self, instance, rescue=False, network_info=None,
                          block_device_mapping=None):
        block_device_mapping = block_device_mapping or []
        # TODO(adiantum) remove network_info creation code
        # when multinics will be completed
        if not network_info:
            network_info = netutils.get_network_info(instance)

        nics = []
        for (network, mapping) in network_info:
            nics.append(self.vif_driver.plug(instance, network, mapping))
        # FIXME(vish): stick this in db
        inst_type_id = instance['instance_type_id']
        inst_type = instance_types.get_instance_type(inst_type_id)

        if FLAGS.use_cow_images:
            driver_type = 'qcow2'
        else:
            driver_type = 'raw'

        for vol in block_device_mapping:
            vol['mount_device'] = _strip_dev(vol['mount_device'])
            (vol['type'], vol['protocol'], vol['name']) = \
                self._get_volume_device_info(vol['device_path'])

        ebs_root = self._volume_in_mapping(self.root_mount_device,
                                           block_device_mapping)
        if self._volume_in_mapping(self.local_mount_device,
                                   block_device_mapping):
            local_gb = False
        else:
            local_gb = inst_type['local_gb']

        xml_info = {'type': FLAGS.libvirt_type,
                    'name': instance['name'],
                    'basepath': os.path.join(FLAGS.instances_path,
                                             instance['name']),
                    'memory_kb': inst_type['memory_mb'] * 1024,
                    'vcpus': inst_type['vcpus'],
                    'rescue': rescue,
                    'local': local_gb,
                    'driver_type': driver_type,
                    'vif_type': FLAGS.libvirt_vif_type,
                    'nics': nics,
                    'ebs_root': ebs_root,
                    'volumes': block_device_mapping}

        if FLAGS.vnc_enabled and FLAGS.libvirt_type not in ('lxc', 'uml'):
            xml_info['vncserver_host'] = FLAGS.vncserver_host
            xml_info['vnc_keymap'] = FLAGS.vnc_keymap
        if not rescue:
            if instance['kernel_id']:
                xml_info['kernel'] = xml_info['basepath'] + "/kernel"

            if instance['ramdisk_id']:
                xml_info['ramdisk'] = xml_info['basepath'] + "/ramdisk"

            xml_info['disk'] = xml_info['basepath'] + "/disk"
        return xml_info

    def to_xml(self, instance, rescue=False, network_info=None,
               block_device_mapping=None):
        block_device_mapping = block_device_mapping or []
        # TODO(termie): cache?
        LOG.debug(_('instance %s: starting toXML method'), instance['name'])
        xml_info = self._prepare_xml_info(instance, rescue, network_info,
                                          block_device_mapping)
        xml = str(Template(self.libvirt_xml, searchList=[xml_info]))
        LOG.debug(_('instance %s: finished toXML method'), instance['name'])
        return xml

    def _lookup_by_name(self, instance_name):
        """Retrieve libvirt domain object given an instance name.

        All libvirt error handling should be handled in this method and
        relevant nova exceptions should be raised in response.

        """
        try:
            return self._conn.lookupByName(instance_name)
        except libvirt.libvirtError as ex:
            error_code = ex.get_error_code()
            if error_code == libvirt.VIR_ERR_NO_DOMAIN:
                raise exception.InstanceNotFound(instance_id=instance_name)

            msg = _("Error from libvirt while looking up %(instance_name)s: "
                    "[Error Code %(error_code)s] %(ex)s") % locals()
            raise exception.Error(msg)

    def get_info(self, instance_name):
        """Retrieve information from libvirt for a specific instance name.

        If a libvirt error is encountered during lookup, we might raise a
        NotFound exception or Error exception depending on how severe the
        libvirt error is.

        """
        virt_dom = self._lookup_by_name(instance_name)
        (state, max_mem, mem, num_cpu, cpu_time) = virt_dom.info()
        return {'state': state,
                'max_mem': max_mem,
                'mem': mem,
                'num_cpu': num_cpu,
                'cpu_time': cpu_time}

    def _create_new_domain(self, xml, persistent=True, launch_flags=0):
        # NOTE(justinsb): libvirt has two types of domain:
        # * a transient domain disappears when the guest is shutdown
        # or the host is rebooted.
        # * a permanent domain is not automatically deleted
        # NOTE(justinsb): Even for ephemeral instances, transient seems risky

        if persistent:
            # To create a persistent domain, first define it, then launch it.
            domain = self._conn.defineXML(xml)

            domain.createWithFlags(launch_flags)
        else:
            # createXML call creates a transient domain
            domain = self._conn.createXML(xml, launch_flags)

        return domain

    def get_diagnostics(self, instance_name):
        raise exception.ApiError(_("diagnostics are not supported "
                                   "for libvirt"))

    def get_disks(self, instance_name):
        """
        Note that this function takes an instance name.

        Returns a list of all block devices for this domain.
        """
        domain = self._lookup_by_name(instance_name)
        # TODO(devcamcar): Replace libxml2 with etree.
        xml = domain.XMLDesc(0)
        doc = None

        try:
            doc = libxml2.parseDoc(xml)
        except Exception:
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

                if devdst is None:
                    continue

                disks.append(devdst)
        finally:
            if ctx is not None:
                ctx.xpathFreeContext()
            if doc is not None:
                doc.freeDoc()

        return disks

    def get_interfaces(self, instance_name):
        """
        Note that this function takes an instance name.

        Returns a list of all network interfaces for this instance.
        """
        domain = self._lookup_by_name(instance_name)
        # TODO(devcamcar): Replace libxml2 with etree.
        xml = domain.XMLDesc(0)
        doc = None

        try:
            doc = libxml2.parseDoc(xml)
        except Exception:
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

                if devdst is None:
                    continue

                interfaces.append(devdst)
        finally:
            if ctx is not None:
                ctx.xpathFreeContext()
            if doc is not None:
                doc.freeDoc()

        return interfaces

    def get_vcpu_total(self):
        """Get vcpu number of physical computer.

        :returns: the number of cpu core.

        """

        # On certain platforms, this will raise a NotImplementedError.
        try:
            return multiprocessing.cpu_count()
        except NotImplementedError:
            LOG.warn(_("Cannot get the number of cpu, because this "
                       "function is not implemented for this platform. "
                       "This error can be safely ignored for now."))
            return 0

    def get_memory_mb_total(self):
        """Get the total memory size(MB) of physical computer.

        :returns: the total amount of memory(MB).

        """

        if sys.platform.upper() != 'LINUX2':
            return 0

        meminfo = open('/proc/meminfo').read().split()
        idx = meminfo.index('MemTotal:')
        # transforming kb to mb.
        return int(meminfo[idx + 1]) / 1024

    def get_local_gb_total(self):
        """Get the total hdd size(GB) of physical computer.

        :returns:
            The total amount of HDD(GB).
            Note that this value shows a partition where
            NOVA-INST-DIR/instances mounts.

        """

        hddinfo = os.statvfs(FLAGS.instances_path)
        return hddinfo.f_frsize * hddinfo.f_blocks / 1024 / 1024 / 1024

    def get_vcpu_used(self):
        """ Get vcpu usage number of physical computer.

        :returns: The total number of vcpu that currently used.

        """

        total = 0
        for dom_id in self._conn.listDomainsID():
            dom = self._conn.lookupByID(dom_id)
            total += len(dom.vcpus()[1])
        return total

    def get_memory_mb_used(self):
        """Get the free memory size(MB) of physical computer.

        :returns: the total usage of memory(MB).

        """

        if sys.platform.upper() != 'LINUX2':
            return 0

        m = open('/proc/meminfo').read().split()
        idx1 = m.index('MemFree:')
        idx2 = m.index('Buffers:')
        idx3 = m.index('Cached:')
        avail = (int(m[idx1 + 1]) + int(m[idx2 + 1]) + int(m[idx3 + 1])) / 1024
        return  self.get_memory_mb_total() - avail

    def get_local_gb_used(self):
        """Get the free hdd size(GB) of physical computer.

        :returns:
           The total usage of HDD(GB).
           Note that this value shows a partition where
           NOVA-INST-DIR/instances mounts.

        """

        hddinfo = os.statvfs(FLAGS.instances_path)
        avail = hddinfo.f_frsize * hddinfo.f_bavail / 1024 / 1024 / 1024
        return self.get_local_gb_total() - avail

    def get_hypervisor_type(self):
        """Get hypervisor type.

        :returns: hypervisor type (ex. qemu)

        """

        return self._conn.getType()

    def get_hypervisor_version(self):
        """Get hypervisor version.

        :returns: hypervisor version (ex. 12003)

        """

        # NOTE(justinsb): getVersion moved between libvirt versions
        # Trying to do be compatible with older versions is a lost cause
        # But ... we can at least give the user a nice message
        method = getattr(self._conn, 'getVersion', None)
        if method is None:
            raise exception.Error(_("libvirt version is too old"
                                    " (does not support getVersion)"))
            # NOTE(justinsb): If we wanted to get the version, we could:
            # method = getattr(libvirt, 'getVersion', None)
            # NOTE(justinsb): This would then rely on a proper version check

        return method()

    def get_cpu_info(self):
        """Get cpuinfo information.

        Obtains cpu feature from virConnect.getCapabilities,
        and returns as a json string.

        :return: see above description

        """

        xml = self._conn.getCapabilities()
        xml = libxml2.parseDoc(xml)
        nodes = xml.xpathEval('//host/cpu')
        if len(nodes) != 1:
            reason = _("'<cpu>' must be 1, but %d\n") % len(nodes)
            reason += xml.serialize()
            raise exception.InvalidCPUInfo(reason=reason)

        cpu_info = dict()

        arch_nodes = xml.xpathEval('//host/cpu/arch')
        if arch_nodes:
            cpu_info['arch'] = arch_nodes[0].getContent()

        model_nodes = xml.xpathEval('//host/cpu/model')
        if model_nodes:
            cpu_info['model'] = model_nodes[0].getContent()

        vendor_nodes = xml.xpathEval('//host/cpu/vendor')
        if vendor_nodes:
            cpu_info['vendor'] = vendor_nodes[0].getContent()

        topology_nodes = xml.xpathEval('//host/cpu/topology')
        topology = dict()
        if topology_nodes:
            topology_node = topology_nodes[0].get_properties()
            while topology_node:
                name = topology_node.get_name()
                topology[name] = topology_node.getContent()
                topology_node = topology_node.get_next()

            keys = ['cores', 'sockets', 'threads']
            tkeys = topology.keys()
            if set(tkeys) != set(keys):
                ks = ', '.join(keys)
                reason = _("topology (%(topology)s) must have %(ks)s")
                raise exception.InvalidCPUInfo(reason=reason % locals())

        feature_nodes = xml.xpathEval('//host/cpu/feature')
        features = list()
        for nodes in feature_nodes:
            features.append(nodes.get_properties().getContent())

        cpu_info['topology'] = topology
        cpu_info['features'] = features
        return utils.dumps(cpu_info)

    def block_stats(self, instance_name, disk):
        """
        Note that this function takes an instance name.
        """
        domain = self._lookup_by_name(instance_name)
        return domain.blockStats(disk)

    def interface_stats(self, instance_name, interface):
        """
        Note that this function takes an instance name.
        """
        domain = self._lookup_by_name(instance_name)
        return domain.interfaceStats(interface)

    def get_console_pool_info(self, console_type):
        #TODO(mdragon): console proxy should be implemented for libvirt,
        #               in case someone wants to use it with kvm or
        #               such. For now return fake data.
        return  {'address': '127.0.0.1',
                 'username': 'fakeuser',
                 'password': 'fakepassword'}

    def refresh_security_group_rules(self, security_group_id):
        self.firewall_driver.refresh_security_group_rules(security_group_id)

    def refresh_security_group_members(self, security_group_id):
        self.firewall_driver.refresh_security_group_members(security_group_id)

    def refresh_provider_fw_rules(self):
        self.firewall_driver.refresh_provider_fw_rules()

    def update_available_resource(self, ctxt, host):
        """Updates compute manager resource info on ComputeNode table.

        This method is called when nova-coompute launches, and
        whenever admin executes "nova-manage service update_resource".

        :param ctxt: security context
        :param host: hostname that compute manager is currently running

        """

        try:
            service_ref = db.service_get_all_compute_by_host(ctxt, host)[0]
        except exception.NotFound:
            raise exception.ComputeServiceUnavailable(host=host)

        # Updating host information
        dic = {'vcpus': self.get_vcpu_total(),
               'memory_mb': self.get_memory_mb_total(),
               'local_gb': self.get_local_gb_total(),
               'vcpus_used': self.get_vcpu_used(),
               'memory_mb_used': self.get_memory_mb_used(),
               'local_gb_used': self.get_local_gb_used(),
               'hypervisor_type': self.get_hypervisor_type(),
               'hypervisor_version': self.get_hypervisor_version(),
               'cpu_info': self.get_cpu_info()}

        compute_node_ref = service_ref['compute_node']
        if not compute_node_ref:
            LOG.info(_('Compute_service record created for %s ') % host)
            dic['service_id'] = service_ref['id']
            db.compute_node_create(ctxt, dic)
        else:
            LOG.info(_('Compute_service record updated for %s ') % host)
            db.compute_node_update(ctxt, compute_node_ref[0]['id'], dic)

    def compare_cpu(self, cpu_info):
        """Checks the host cpu is compatible to a cpu given by xml.

        "xml" must be a part of libvirt.openReadonly().getCapabilities().
        return values follows by virCPUCompareResult.
        if 0 > return value, do live migration.
        'http://libvirt.org/html/libvirt-libvirt.html#virCPUCompareResult'

        :param cpu_info: json string that shows cpu feature(see get_cpu_info())
        :returns:
            None. if given cpu info is not compatible to this server,
            raise exception.

        """

        LOG.info(_('Instance launched has CPU info:\n%s') % cpu_info)
        dic = utils.loads(cpu_info)
        xml = str(Template(self.cpuinfo_xml, searchList=dic))
        LOG.info(_('to xml...\n:%s ' % xml))

        u = "http://libvirt.org/html/libvirt-libvirt.html#virCPUCompareResult"
        m = _("CPU doesn't have compatibility.\n\n%(ret)s\n\nRefer to %(u)s")
        # unknown character exists in xml, then libvirt complains
        try:
            ret = self._conn.compareCPU(xml, 0)
        except libvirt.libvirtError, e:
            ret = e.message
            LOG.error(m % locals())
            raise

        if ret <= 0:
            raise exception.InvalidCPUInfo(reason=m % locals())

        return

    def ensure_filtering_rules_for_instance(self, instance_ref,
                                            time=None):
        """Setting up filtering rules and waiting for its completion.

        To migrate an instance, filtering rules to hypervisors
        and firewalls are inevitable on destination host.
        ( Waiting only for filterling rules to hypervisor,
        since filtering rules to firewall rules can be set faster).

        Concretely, the below method must be called.
        - setup_basic_filtering (for nova-basic, etc.)
        - prepare_instance_filter(for nova-instance-instance-xxx, etc.)

        to_xml may have to be called since it defines PROJNET, PROJMASK.
        but libvirt migrates those value through migrateToURI(),
        so , no need to be called.

        Don't use thread for this method since migration should
        not be started when setting-up filtering rules operations
        are not completed.

        :params instance_ref: nova.db.sqlalchemy.models.Instance object

        """

        if not time:
            time = greenthread

        # If any instances never launch at destination host,
        # basic-filtering must be set here.
        self.firewall_driver.setup_basic_filtering(instance_ref)
        # setting up n)ova-instance-instance-xx mainly.
        self.firewall_driver.prepare_instance_filter(instance_ref)

        # wait for completion
        timeout_count = range(FLAGS.live_migration_retry_count)
        while timeout_count:
            if self.firewall_driver.instance_filter_exists(instance_ref):
                break
            timeout_count.pop()
            if len(timeout_count) == 0:
                msg = _('Timeout migrating for %s. nwfilter not found.')
                raise exception.Error(msg % instance_ref.name)
            time.sleep(1)

    def live_migration(self, ctxt, instance_ref, dest,
                       post_method, recover_method):
        """Spawning live_migration operation for distributing high-load.

        :params ctxt: security context
        :params instance_ref:
            nova.db.sqlalchemy.models.Instance object
            instance object that is migrated.
        :params dest: destination host
        :params post_method:
            post operation method.
            expected nova.compute.manager.post_live_migration.
        :params recover_method:
            recovery method when any exception occurs.
            expected nova.compute.manager.recover_live_migration.

        """

        greenthread.spawn(self._live_migration, ctxt, instance_ref, dest,
                          post_method, recover_method)

    def _live_migration(self, ctxt, instance_ref, dest,
                        post_method, recover_method):
        """Do live migration.

        :params ctxt: security context
        :params instance_ref:
            nova.db.sqlalchemy.models.Instance object
            instance object that is migrated.
        :params dest: destination host
        :params post_method:
            post operation method.
            expected nova.compute.manager.post_live_migration.
        :params recover_method:
            recovery method when any exception occurs.
            expected nova.compute.manager.recover_live_migration.

        """

        # Do live migration.
        try:
            flaglist = FLAGS.live_migration_flag.split(',')
            flagvals = [getattr(libvirt, x.strip()) for x in flaglist]
            logical_sum = reduce(lambda x, y: x | y, flagvals)

            if self.read_only:
                tmpconn = self._connect(self.libvirt_uri, False)
                dom = tmpconn.lookupByName(instance_ref.name)
                dom.migrateToURI(FLAGS.live_migration_uri % dest,
                                 logical_sum,
                                 None,
                                 FLAGS.live_migration_bandwidth)
                tmpconn.close()
            else:
                dom = self._conn.lookupByName(instance_ref.name)
                dom.migrateToURI(FLAGS.live_migration_uri % dest,
                                 logical_sum,
                                 None,
                                 FLAGS.live_migration_bandwidth)

        except Exception:
            recover_method(ctxt, instance_ref, dest=dest)
            raise

        # Waiting for completion of live_migration.
        timer = utils.LoopingCall(f=None)

        def wait_for_live_migration():
            """waiting for live migration completion"""
            try:
                self.get_info(instance_ref.name)['state']
            except exception.NotFound:
                timer.stop()
                post_method(ctxt, instance_ref, dest)

        timer.f = wait_for_live_migration
        timer.start(interval=0.5, now=True)

    def unfilter_instance(self, instance_ref, network_info):
        """See comments of same method in firewall_driver."""
        self.firewall_driver.unfilter_instance(instance_ref,
                                               network_info=network_info)

    def update_host_status(self):
        """See xenapi_conn.py implementation."""
        pass

    def get_host_stats(self, refresh=False):
        """See xenapi_conn.py implementation."""
        pass

    def set_host_enabled(self, host, enabled):
        """Sets the specified host's ability to accept new instances."""
        pass
