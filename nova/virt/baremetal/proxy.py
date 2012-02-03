# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 University of Southern California
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
#
"""
A connection to a hypervisor through baremetal.

**Related Flags**

:baremetal_type:  Baremetal domain type.
:baremetal_uri:  Override for the default baremetal URI (baremetal_type).
:rescue_image_id:  Rescue ami image (default: ami-rescue).
:rescue_kernel_id:  Rescue aki image (default: aki-rescue).
:rescue_ramdisk_id:  Rescue ari image (default: ari-rescue).
:injected_network_template:  Template file for injected network
:allow_project_net_traffic:  Whether to allow in project network traffic

"""

import hashlib
import os
import shutil
import time

from nova import context as nova_context
from nova import db
from nova import exception
from nova import flags
from nova import log as logging
from nova import utils
from nova.openstack.common import cfg
from nova.compute import instance_types
from nova.compute import power_state
from nova.compute import vm_states
from nova.virt import disk
from nova.virt.disk import api as disk
from nova.virt import driver
from nova.virt.baremetal import nodes
from nova.virt.baremetal import dom
from nova.virt.libvirt import utils as libvirt_utils


Template = None

LOG = logging.getLogger(__name__)

FLAGS = flags.FLAGS

baremetal_opts = [
    cfg.StrOpt('baremetal_injected_network_template',
                default=utils.abspath('virt/interfaces.template'),
                help='Template file for injected network'),
    cfg.StrOpt('baremetal_type',
                default='baremetal',
                help='baremetal domain type'),
    cfg.StrOpt('baremetal_uri',
                default='',
                help='Override the default baremetal URI'),
    cfg.BoolOpt('baremetal_allow_project_net_traffic',
                 default=True,
                 help='Whether to allow in project network traffic')
    ]

FLAGS.register_opts(baremetal_opts)


def get_connection(read_only):
    # These are loaded late so that there's no need to install these
    # libraries when not using baremetal.
    # Cheetah is separate because the unit tests want to load Cheetah,
    # but not baremetal.
    _late_load_cheetah()
    return ProxyConnection(read_only)


def _late_load_cheetah():
    global Template
    if Template is None:
        t = __import__('Cheetah.Template', globals(), locals(),
                       ['Template'], -1)
        Template = t.Template


class ProxyConnection(driver.ComputeDriver):

    def __init__(self, read_only):
        super(ProxyConnection, self).__init__()
        self.baremetal_nodes = nodes.get_baremetal_nodes()
        self._wrapped_conn = None
        self.read_only = read_only
        self._host_state = None

    @property
    def HostState(self):
        if not self._host_state:
            self._host_state = HostState(self.read_only)
        return self._host_state

    def init_host(self, host):
        pass

    def _get_connection(self):
        self._wrapped_conn = dom.BareMetalDom()
        return self._wrapped_conn
    _conn = property(_get_connection)

    def get_pty_for_instance(self, instance_name):
        raise NotImplementedError()

    def list_instances(self):
        return self._conn.list_domains()

    def _map_to_instance_info(self, domain_name):
        """Gets info from a virsh domain object into an InstanceInfo"""
        (state, _max_mem, _mem, _num_cpu, _cpu_time) \
            = self._conn.get_domain_info(domain_name)
        name = domain_name
        return driver.InstanceInfo(name, state)

    def list_instances_detail(self):
        infos = []
        for domain_name in self._conn.list_domains():
            info = self._map_to_instance_info(domain_name)
            infos.append(info)
        return infos

    def destroy(self, instance, network_info, block_device_info=None,
                cleanup=True):
        timer = utils.LoopingCall(f=None)

        while True:
            try:
                self._conn.destroy_domain(instance['name'])
                break
            except Exception as ex:
                msg = (_("Error encountered when destroying instance "
                        "'%(name)s': %(ex)s") %
                        {"name": instance["name"], "ex": ex})
                LOG.debug(msg)
                break

        if cleanup:
            self._cleanup(instance)

        return True

    def _cleanup(self, instance):
        target = os.path.join(FLAGS.instances_path, instance['name'])
        instance_name = instance['name']
        LOG.info(_('instance %(instance_name)s: deleting instance files'
                ' %(target)s') % locals())
        if FLAGS.baremetal_type == 'lxc':
            disk.destroy_container(self.container)
        if os.path.exists(target):
            shutil.rmtree(target)

    @exception.wrap_exception
    def attach_volume(self, instance_name, device_path, mountpoint):
        raise exception.APIError("attach_volume not supported for baremetal.")

    @exception.wrap_exception
    def detach_volume(self, instance_name, mountpoint):
        raise exception.APIError("detach_volume not supported for baremetal.")

    @exception.wrap_exception
    def snapshot(self, instance, image_id):
        raise exception.APIError("snapshot not supported for baremetal.")

    @exception.wrap_exception
    def reboot(self, instance):
        timer = utils.LoopingCall(f=None)

        def _wait_for_reboot():
            try:
                state = self._conn.reboot_domain(instance['name'])
                if state == power_state.RUNNING:
                    LOG.debug(_('instance %s: rebooted'), instance['name'])
                    timer.stop()
            except:
                LOG.exception(_('_wait_for_reboot failed'))
                timer.stop()
        timer.f = _wait_for_reboot
        return timer.start(interval=0.5, now=True)

    @exception.wrap_exception
    def rescue(self, context, instance, network_info):
        """Loads a VM using rescue images.

        A rescue is normally performed when something goes wrong with the
        primary images and data needs to be corrected/recovered. Rescuing
        should not edit or over-ride the original image, only allow for
        data recovery.

        """
        self.destroy(instance, False)

        xml_dict = self.to_xml_dict(instance, rescue=True)
        rescue_images = {'image_id': FLAGS.baremetal_rescue_image_id,
                         'kernel_id': FLAGS.baremetal_rescue_kernel_id,
                         'ramdisk_id': FLAGS.baremetal_rescue_ramdisk_id}
        self._create_image(instance, '.rescue', rescue_images,
                           network_info=network_info)

        timer = utils.LoopingCall(f=None)

        def _wait_for_rescue():
            try:
                state = self._conn.reboot_domain(instance['name'])
                if state == power_state.RUNNING:
                    LOG.debug(_('instance %s: rescued'), instance['name'])
                    timer.stop()
            except:
                LOG.exception(_('_wait_for_rescue failed'))
                timer.stop()
        timer.f = _wait_for_reboot
        return timer.start(interval=0.5, now=True)

    @exception.wrap_exception
    def unrescue(self, instance, network_info):
        """Reboot the VM which is being rescued back into primary images.

        Because reboot destroys and re-creates instances, unresue should
        simply call reboot.

        """
        self.reboot(instance)

    def spawn(self, context, instance, image_meta, network_info,
              block_device_info=None):
        LOG.debug(_("<============= spawn of baremetal =============>"))

        def basepath(fname='', suffix=''):
            return os.path.join(FLAGS.instances_path,
                                instance['name'],
                                fname + suffix)
        bpath = basepath(suffix='')
        timer = utils.LoopingCall(f=None)

        xml_dict = self.to_xml_dict(instance, network_info)
        self._create_image(context, instance, xml_dict,
            network_info=network_info,
            block_device_info=block_device_info)
        LOG.debug(_("instance %s: is building"), instance['name'])
        LOG.debug(_(xml_dict))

        def _wait_for_boot():
            try:
                LOG.debug(_("Key is injected but instance is not running yet"))
                db.instance_update(context, instance['id'],
                    {'vm_state': vm_states.BUILDING})
                state = self._conn.create_domain(xml_dict, bpath)
                if state == power_state.RUNNING:
                    LOG.debug(_('instance %s: booted'), instance['name'])
                    db.instance_update(context, instance['id'],
                            {'vm_state': vm_states.ACTIVE})
                    LOG.debug(_('~~~~~~ current state = %s ~~~~~~'), state)
                    LOG.debug(_("instance %s spawned successfully"),
                            instance['name'])
                else:
                    LOG.debug(_('instance %s:not booted'), instance['name'])
            except Exception as Exn:
                LOG.debug(_("Bremetal assignment is overcommitted."))
                db.instance_update(context, instance['id'],
                           {'vm_state': vm_states.OVERCOMMIT,
                            'power_state': power_state.SUSPENDED})
            timer.stop()
        timer.f = _wait_for_boot

        return timer.start(interval=0.5, now=True)

    def get_console_output(self, instance):
        console_log = os.path.join(FLAGS.instances_path, instance['name'],
                                   'console.log')

        libvirt_utils.chown(console_log, os.getuid())

        fd = self._conn.find_domain(instance['name'])

        self.baremetal_nodes.get_console_output(console_log, fd['node_id'])

        fpath = console_log

        return libvirt_utils.load_file(fpath)

    @exception.wrap_exception
    def get_ajax_console(self, instance):
        raise NotImplementedError()

    @exception.wrap_exception
    def get_vnc_console(self, instance):
        raise NotImplementedError()

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
                libvirt_utils.ensure_tree(base_dir)
            base = os.path.join(base_dir, fname)

            @utils.synchronized(fname)
            def call_if_not_exists(base, fn, *args, **kwargs):
                if not os.path.exists(base):
                    fn(target=base, *args, **kwargs)

            call_if_not_exists(base, fn, *args, **kwargs)

            if cow:
                libvirt_utils.create_cow_image(base, target)
            else:
                libvirt_utils.copy_image(base, target)

    def _create_image(self, context, inst, xml, suffix='',
                      disk_images=None, network_info=None,
                      block_device_info=None):
        if not suffix:
            suffix = ''

        # syntactic nicety
        def basepath(fname='', suffix=suffix):
            return os.path.join(FLAGS.instances_path,
                                inst['name'],
                                fname + suffix)

        # ensure directories exist and are writable
        libvirt_utils.ensure_tree(basepath(suffix=''))
        utils.execute('chmod', '0777', basepath(suffix=''))

        LOG.info(_('instance %s: Creating image'), inst['name'])

        if FLAGS.baremetal_type == 'lxc':
            container_dir = '%s/rootfs' % basepath(suffix='')
            libvirt_utils.ensure_tree(container_dir)

        # NOTE(vish): No need add the suffix to console.log
        libvirt_utils.write_to_file(basepath('console.log', ''), '', 007)

        if not disk_images:
            disk_images = {'image_id': inst['image_ref'],
                           'kernel_id': inst['kernel_id'],
                           'ramdisk_id': inst['ramdisk_id']}

        if disk_images['kernel_id']:
            fname = disk_images['kernel_id']
            self._cache_image(fn=libvirt_utils.fetch_image,
                              context=context,
                              target=basepath('kernel'),
                              fname=fname,
                              cow=False,
                              image_id=disk_images['kernel_id'],
                              user_id=inst['user_id'],
                              project_id=inst['project_id'])
            if disk_images['ramdisk_id']:
                fname = disk_images['ramdisk_id']
                self._cache_image(fn=libvirt_utils.fetch_image,
                                  context=context,
                                  target=basepath('ramdisk'),
                                  fname=fname,
                                  cow=False,
                                  image_id=disk_images['ramdisk_id'],
                                  user_id=inst['user_id'],
                                  project_id=inst['project_id'])

        root_fname = hashlib.sha1(str(disk_images['image_id'])).hexdigest()
        size = inst['root_gb'] * 1024 * 1024 * 1024

        inst_type_id = inst['instance_type_id']
        inst_type = instance_types.get_instance_type(inst_type_id)
        if inst_type['name'] == 'm1.tiny' or suffix == '.rescue':
            size = None
            root_fname += "_sm"
        else:
            root_fname += "_%d" % inst['root_gb']

        self._cache_image(fn=libvirt_utils.fetch_image,
                          context=context,
                          target=basepath('root'),
                          fname=root_fname,
                          cow=False,  # FLAGS.use_cow_images,
                          image_id=disk_images['image_id'],
                          user_id=inst['user_id'],
                          project_id=inst['project_id'],
                          size=size)

        # For now, we assume that if we're not using a kernel, we're using a
        # partitioned disk image where the target partition is the first
        # partition
        target_partition = None
        if not inst['kernel_id']:
            target_partition = "1"

        if FLAGS.baremetal_type == 'lxc':
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
                gateway_v6 = mapping['gateway_v6']
            net_info = {'name': 'eth%d' % ifc_num,
                   'address': address,
                   'netmask': netmask,
                   'gateway': mapping['gateway'],
                   'broadcast': mapping['broadcast'],
                   'dns': ' '.join(mapping['dns']),
                   'address_v6': address_v6,
                   'gateway_v6': gateway_v6,
                   'netmask_v6': netmask_v6}
            nets.append(net_info)

        if have_injected_networks:
            net = str(Template(ifc_template,
                               searchList=[{'interfaces': nets,
                                            'use_ipv6': FLAGS.use_ipv6}]))

        metadata = inst.get('metadata')
        if any((key, net, metadata)):
            inst_name = inst['name']

            injection_path = basepath('root')
            img_id = inst.image_ref
            disable_auto_fsck = True

            for injection in ('metadata', 'key', 'net'):
                if locals()[injection]:
                    LOG.info(_('instance %(inst_name)s: injecting '
                               '%(injection)s into image %(img_id)s'
                               % locals()))
            try:
                disk.inject_data(injection_path, key, net, metadata,
                                 partition=target_partition,
                                 use_cow=False,  # FLAGS.use_cow_images,
                                 disable_auto_fsck=disable_auto_fsck)

            except Exception as e:
                # This could be a windows image, or a vmdk format disk
                LOG.warn(_('instance %(inst_name)s: ignoring error injecting'
                        ' data into image %(img_id)s (%(e)s)') % locals())

    def _prepare_xml_info(self, instance, network_info, rescue,
                          block_device_info=None):
        # block_device_mapping = driver.block_device_info_get_mapping(
        #    block_device_info)
        map = 0
        for (network, mapping) in network_info:
            map += 1

        nics = []
        # FIXME(vish): stick this in db
        inst_type_id = instance['instance_type_id']
        inst_type = instance_types.get_instance_type(inst_type_id)

        driver_type = 'raw'

        xml_info = {'type': FLAGS.baremetal_type,
                    'name': instance['name'],
                    'basepath': os.path.join(FLAGS.instances_path,
                                             instance['name']),
                    'memory_kb': inst_type['memory_mb'] * 1024,
                    'vcpus': inst_type['vcpus'],
                    'rescue': rescue,
                    'driver_type': driver_type,
                    'nics': nics,
                    'ip_address': mapping['ips'][0]['ip'],
                    'mac_address': mapping['mac'],
                    'user_data': instance['user_data'],
                    'image_id': instance['image_ref'],
                    'kernel_id': instance['kernel_id'],
                    'ramdisk_id': instance['ramdisk_id']}

        if not rescue:
            if instance['kernel_id']:
                xml_info['kernel'] = xml_info['basepath'] + "/kernel"

            if instance['ramdisk_id']:
                xml_info['ramdisk'] = xml_info['basepath'] + "/ramdisk"

            xml_info['disk'] = xml_info['basepath'] + "/disk"
        return xml_info

    def to_xml_dict(self, instance, rescue=False, network_info=None):
        LOG.debug(_('instance %s: starting toXML method'), instance['name'])
        xml_info = self._prepare_xml_info(instance, rescue, network_info)
        LOG.debug(_('instance %s: finished toXML method'), instance['name'])
        return xml_info

    def get_info(self, instance_name):
        """Retrieve information from baremetal for a specific instance name.

        If a baremetal error is encountered during lookup, we might raise a
        NotFound exception or Error exception depending on how severe the
        baremetal error is.

        """
        (state, max_mem, mem, num_cpu, cpu_time) \
                = self._conn.get_domain_info(instance_name)
        return {'state': state,
                'max_mem': max_mem,
                'mem': mem,
                'num_cpu': num_cpu,
                'cpu_time': cpu_time}

    def _create_new_domain(self, persistent=True, launch_flags=0):
        raise NotImplementedError()

    def get_diagnostics(self, instance_name):
        # diagnostics are not supported for baremetal
        raise NotImplementedError()

    def get_disks(self, instance_name):
        raise NotImplementedError()

    def get_interfaces(self, instance_name):
        raise NotImplementedError()

    def get_vcpu_total(self):
        """Get vcpu number of physical computer.

        :returns: the number of cpu core.

        """

        # On certain platforms, this will raise a NotImplementedError.
        try:
            return self.baremetal_nodes.get_hw_info('vcpus')
        except NotImplementedError:
            LOG.warn(_("Cannot get the number of cpu, because this "
                       "function is not implemented for this platform. "
                       "This error can be safely ignored for now."))
            return False

    def get_memory_mb_total(self):
        """Get the total memory size(MB) of physical computer.

        :returns: the total amount of memory(MB).

        """
        return self.baremetal_nodes.get_hw_info('memory_mb')

    def get_local_gb_total(self):
        """Get the total hdd size(GB) of physical computer.

        :returns:
            The total amount of HDD(GB).
            Note that this value shows a partition where
            NOVA-INST-DIR/instances mounts.

        """
        return self.baremetal_nodes.get_hw_info('local_gb')

    def get_vcpu_used(self):
        """ Get vcpu usage number of physical computer.

        :returns: The total number of vcpu that currently used.

        """

        total = 0
        for dom_id in self._conn.list_domains():
            total += 1
        return total

    def get_memory_mb_used(self):
        """Get the free memory size(MB) of physical computer.

        :returns: the total usage of memory(MB).

        """
        return self.baremetal_nodes.get_hw_info('memory_mb_used')

    def get_local_gb_used(self):
        """Get the free hdd size(GB) of physical computer.

        :returns:
           The total usage of HDD(GB).
           Note that this value shows a partition where
           NOVA-INST-DIR/instances mounts.

        """
        return self.baremetal_nodes.get_hw_info('local_gb_used')

    def get_hypervisor_type(self):
        """Get hypervisor type.

        :returns: hypervisor type (ex. qemu)

        """
        return self.baremetal_nodes.get_hw_info('hypervisor_type')

    def get_hypervisor_version(self):
        """Get hypervisor version.

        :returns: hypervisor version (ex. 12003)

        """
        return self.baremetal_nodes.get_hw_info('hypervisor_version')

    def get_cpu_info(self):
        """Get cpuinfo information.

        Obtains cpu feature from virConnect.getCapabilities,
        and returns as a json string.

        :return: see above description

        """
        return self.baremetal_nodes.get_hw_info('cpu_info')

    def block_stats(self, instance_name, disk):
        raise NotImplementedError()

    def interface_stats(self, instance_name, interface):
        raise NotImplementedError()

    def get_console_pool_info(self, console_type):
        #TODO(mdragon): console proxy should be implemented for baremetal,
        #               in case someone wants to use it.
        #               For now return fake data.
        return  {'address': '127.0.0.1',
                 'username': 'fakeuser',
                 'password': 'fakepassword'}

    def refresh_security_group_rules(self, security_group_id):
        # Bare metal doesn't currently support security groups
        pass

    def refresh_security_group_members(self, security_group_id):
        # Bare metal doesn't currently support security groups
        pass

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
               'cpu_info': self.get_cpu_info(),
               'cpu_arch': FLAGS.cpu_arch,
               'xpu_arch': FLAGS.xpu_arch,
               'xpus': FLAGS.xpus,
               'xpu_info': FLAGS.xpu_info,
               'net_arch': FLAGS.net_arch,
               'net_info': FLAGS.net_info,
               'net_mbps': FLAGS.net_mbps,
               'service_id': service_ref['id']}

        compute_node_ref = service_ref['compute_node']
        LOG.info(_('#### RLK: cpu_arch = %s ') % FLAGS.cpu_arch)
        if not compute_node_ref:
            LOG.info(_('Compute_service record created for %s ') % host)
            dic['service_id'] = service_ref['id']
            db.compute_node_create(ctxt, dic)
        else:
            LOG.info(_('Compute_service record updated for %s ') % host)
            db.compute_node_update(ctxt, compute_node_ref[0]['id'], dic)

    def compare_cpu(self, cpu_info):
        raise NotImplementedError()

    def ensure_filtering_rules_for_instance(self, instance_ref,
                                            time=None):
        raise NotImplementedError()

    def live_migration(self, ctxt, instance_ref, dest,
                       post_method, recover_method):
        raise NotImplementedError()

    def unfilter_instance(self, instance_ref):
        """See comments of same method in firewall_driver."""
        pass

    def update_host_status(self):
        """Update the status info of the host, and return those values
            to the calling program."""
        return self.HostState.update_status()

    def get_host_stats(self, refresh=False):
        """Return the current state of the host. If 'refresh' is
           True, run the update first."""
        LOG.debug(_("Updating!"))
        return self.HostState.get_host_stats(refresh=refresh)


class HostState(object):
    """Manages information about the XenServer host this compute
    node is running on.
    """

    def __init__(self, read_only):
        super(HostState, self).__init__()
        self.read_only = read_only
        self._stats = {}
        self.update_status()

    def get_host_stats(self, refresh=False):
        """Return the current state of the host. If 'refresh' is
        True, run the update first.
        """
        if refresh:
            self.update_status()
        return self._stats

    def update_status(self):
        """
        We can get host status information.
        """
        LOG.debug(_("Updating host stats"))
        connection = get_connection(self.read_only)
        data = {}
        data["vcpus"] = connection.get_vcpu_total()
        data["vcpus_used"] = connection.get_vcpu_used()
        data["cpu_info"] = connection.get_cpu_info()
        data["cpu_arch"] = FLAGS.cpu_arch
        data["xpus"] = FLAGS.xpus
        data["xpu_arch"] = FLAGS.xpu_arch
        data["xpu_info"] = FLAGS.xpu_info
        data["net_arch"] = FLAGS.net_arch
        data["net_info"] = FLAGS.net_info
        data["net_mbps"] = FLAGS.net_mbps
        data["disk_total"] = connection.get_local_gb_total()
        data["disk_used"] = connection.get_local_gb_used()
        data["disk_available"] = data["disk_total"] - data["disk_used"]
        data["host_memory_total"] = connection.get_memory_mb_total()
        data["host_memory_free"] = data["host_memory_total"] - \
            connection.get_memory_mb_used()
        data["hypervisor_type"] = connection.get_hypervisor_type()
        data["hypervisor_version"] = connection.get_hypervisor_version()
        self._stats = data
