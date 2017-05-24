'''

'''

from nova.virt import driver
from nova.compute import power_state
from nova import objects
from nova import image
from nova.virt.vcloud import util
from nova.openstack.common import log as logging
from oslo.config import cfg
from nova.openstack.common import jsonutils
from nova import exception
from pyvcloud.vcloudair import VCA
import subprocess
import os

CONF = cfg.CONF
LOG = logging.getLogger(__name__)



IMAGE_API = image.API()

# for test
def print_vca(vca):
    if vca:
        print 'vca token:            ', vca.token
        if vca.vcloud_session:
            print 'vcloud session token: ', vca.vcloud_session.token
            print 'org name:             ', vca.vcloud_session.org
            print 'org url:              ', vca.vcloud_session.org_url
            print 'organization:         ', vca.vcloud_session.organization
        else:
            print 'vca vcloud session:   ', vca.vcloud_session
    else:
        print 'vca: ', vca

class VCloudNode(object):
    def __init__(self, name, **args):
        self.name = name
        for key in args.keys():
            self.__setattr__(key, args.get(key))

class VMwareVcloudDriver(driver.ComputeDriver):
    """The VCloud host connection object."""


    def __init__(self, virtapi, scheme="https"):
        import  pdb
        pdb.set_trace()
        self.instances = {}
        self.vcloud_nodes = [VCloudNode('vcloud_node_01',
                             vorg_name = 'liuling_org',
                             username = 'liuling',
                             password = 'huawei',
                             vdc_name = 'liuling_org_vdc',
                             vcloud_host = '162.3.110.103')]

        vcloud_node_name = self.vcloud_nodes[0].__getattribute__('name')
        vorg_name = self.vcloud_nodes[0].__getattribute__('vorg_name')
        user_name = self.vcloud_nodes[0].__getattribute__('username')
        password = self.vcloud_nodes[0].__getattribute__('password')
        vdc_name = self.vcloud_nodes[0].__getattribute__('vdc_name')
        vcloud_host = self.vcloud_nodes[0].__getattribute__('vcloud_host')


        # vapp = 'cirrosliuling'

        #sample login sequence on vCloud Air Subscription
        # vca = VCA(host=host, username=username, service_type='vcd', version='5.7', verify=True)
        service = '85-719'
        self.vcloud_managers = {vcloud_node_name:VCA(host=vcloud_host, username=user_name, service_type='vcd', version='5.5', verify=False)}
        vca = self.vcloud_managers.get(vcloud_node_name)

        #first login, with password and org name
        result = vca.login(password=password, org=vorg_name)
        print_vca(vca)
        result = vca.login(token=vca.token, org=vorg_name, org_url=vca.vcloud_session.org_url)
        print_vca(vca)

        super(VMwareVcloudDriver, self).__init__(virtapi)
        

    def _retrieve_network(self):
        # todo: waiting for WANG Jun
        return "liuling_vdc_net"

    def init_host(self, host):
        return
    

    def list_instances(self):
        #TODO
        return self.instances.keys()

    def list_instance_uuids(self):
        return

    def plug_vifs(self, instance, network_info):
        """Plug VIFs into networks."""
        pass

    def unplug_vifs(self, instance, network_info):
        """Unplug VIFs from networks."""
        pass
    

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None):
        #XXX
        import pdb
        pdb.set_trace()
        name = instance['name']
        state = power_state.BUILDING
        
        # 0.get vorg, user name,password vdc  from configuration file (only one org)
#        vorg_name = 'liuling_org'
 #       user_name = 'liuling'
  #      password = 'huawei'
   #     vdc_name = 'liuling_org_vdc'
    #    vcloud_host = '162.3.110.103'

        vcloud_node_name = self.vcloud_nodes[0].__getattribute__('name')
        vorg_name = self.vcloud_nodes[0].__getattribute__('vorg_name')
        user_name = self.vcloud_nodes[0].__getattribute__('username')
        password = self.vcloud_nodes[0].__getattribute__('password')
        vdc_name = self.vcloud_nodes[0].__getattribute__('vdc_name')
        vcloud_host = self.vcloud_nodes[0].__getattribute__('vcloud_host')

        
        # 1.1 get image id, vm info ,flavor info 
        image_uuid = instance.image_ref
        vm_uuid = instance.uuid
        vm_name = instance.name
        vm_hostname = instance.hostname
        vm_instance_type_id = instance.instance_type_id
#         flavor_obj = objects.Flavor.get_by_id(
#             context,
#             vm_instance_type_id)
#         flavor_id = flavor_obj.flavorid       
        
        # 1.2 (optional)get network name
        net_name = self._retrieve_network()

        # 1.3 (optional) 
        is_poweron = True
               
        # 2. download qcow2 file glance to local
        tmp_dir = '/hctemp/'
        metadata = IMAGE_API.get(context, image_uuid)
        file_size = int(metadata['size'])
        read_iter = IMAGE_API.download(context, image_uuid)
        glance_file_handle = util.GlanceFileRead(read_iter)
    
        orig_file_name = tmp_dir + image_uuid +'.tmp'
        orig_file_handle = open(orig_file_name, "wb")
        
        util.start_transfer(context, glance_file_handle, file_size,
                   write_file_handle=orig_file_handle)
        
        
        # 3. convert to vmdk
        if metadata["disk_format"] == 'qcow2':
            converted_file_name = tmp_dir +  'converted-file.vmdk'
            convert_commond = "qemu-img convert -f %s -O %s %s %s" % \
                                    ('qcow2',
                                    'vmdk',
                                    orig_file_name,
                                    converted_file_name)
            convert_result = subprocess.call([convert_commond],shell=True)
            
            if convert_result == 0:
                # do something, change metadata

                ovf_vmdk_name = converted_file_name
                file_size = os.path.getsize(converted_file_name)                      
        else:
            ovf_vmdk_name = orig_file_name
            
        # 4. vmdk to ovf
        ovf_name = '%s%s.ovf' % (tmp_dir,image_uuid)
        vmx_name = '%sbase-%d.vmx' % (tmp_dir,vm_instance_type_id)
        mk_ovf_cmd = "ovftool -o %s %s" % (vmx_name,ovf_name)
        rm_exited_file_cmd = 'rm -f %s' % ovf_name;
        rm_exited_file_result = subprocess.call(rm_exited_file_cmd,shell=True)
        mk_ovf_result = subprocess.call(mk_ovf_cmd,shell=True)
        if mk_ovf_result != 0:
            LOG.error('make ovf faild!')
            return
        
        # 5. upload ovf to vcloud template, using image's uuid as template name
        # 6. create vm from template
        
        ovf_name = '%s%s.ovf' % (tmp_dir,image_uuid)
        vmx_name = '%sbase-%d.vmx' % (tmp_dir,vm_instance_type_id)

        if is_poweron:
            create_vapp_cmd = 'ovftool --powerOn --net:"VM Network=%s" %s "vcloud://%s:%s@%s?org=%s&vdc=%s&vapp=%s"' % \
                            (net_name,
                             ovf_name,
                             user_name,
                             password,
                             vcloud_host,
                             vorg_name,
                             vdc_name,
                             vm_uuid)
        else:
            create_vapp_cmd = 'ovftool --net:"VM Network=%s" %s "vcloud://%s:%s@%s?org=%s&vdc=%s&vapp=%s"' % \
                            (net_name,
                             ovf_name,
                             user_name,
                             password,
                             vcloud_host,
                             vorg_name,
                             vdc_name,
                             vm_uuid)
        
        create_vapp_cmd_result = subprocess.call(create_vapp_cmd,shell=True)
        if mk_ovf_result != 0:
            LOG.error('create vapp faild!')
            return
        
        

    def snapshot(self, context, instance, name, update_task_state):
        pass
#         if instance['name'] not in self.instances:
#             raise exception.InstanceNotRunning(instance_id=instance['uuid'])
#         update_task_state(task_state=task_states.IMAGE_UPLOADING)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        pass
        

    @staticmethod
    def get_host_ip_addr():
        return '192.168.0.1'

    def set_admin_password(self, instance, new_pass):
        pass

    def inject_file(self, instance, b64_path, b64_contents):
        pass

    def resume_state_on_host_boot(self, context, instance, network_info,
                                  block_device_info=None):
        pass

    def rescue(self, context, instance, network_info, image_meta,
               rescue_password):
        pass

    def unrescue(self, instance, network_info):
        pass

    def poll_rebooting_instances(self, timeout, instances):
        pass

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   flavor, network_info,
                                   block_device_info=None,
                                   timeout=0, retry_interval=0):
        pass

    def finish_revert_migration(self, context, instance, network_info,
                                block_device_info=None, power_on=True):
        pass

    def post_live_migration_at_destination(self, context, instance,
                                           network_info,
                                           block_migration=False,
                                           block_device_info=None):
        pass
    

    def power_off(self, instance, shutdown_timeout=0, shutdown_attempts=0):
        #XXX
        import pdb
        pdb.set_trace()
        vca = self.vcloud_managers.get(self.vcloud_nodes[0].name)
        result = vca.login(token=vca.token, org=vca.org, org_url=vca.vcloud_session.org_url)
        if not result:
            LOG.error('login to vloud failed')

        the_vdc = vca.get_vdc(self.vcloud_nodes[0].vdc_name)
        the_vapp = vca.get_vapp(the_vdc, instance.uuid)
        #the_vapp.poweroff()
        the_vapp.undeploy()


    def power_on(self, context, instance, network_info, block_device_info):
        #XXX
        import pdb
        pdb.set_trace()

        vca = self.vcloud_managers.get(self.vcloud_nodes[0].name)
        result = vca.login(token=vca.token, org=vca.org, org_url=vca.vcloud_session.org_url)
        if not result:
            LOG.error('login to vloud failed')

        the_vdc = vca.get_vdc(self.vcloud_nodes[0].vdc_name)
        the_vapp = vca.get_vapp(the_vdc, instance.uuid)
        the_vapp.poweron()


    def soft_delete(self, instance):
        pass

    def restore(self, instance):
        pass

    def pause(self, instance):
        pass

    def unpause(self, instance):
        pass

    def suspend(self, instance):
        pass

    def resume(self, context, instance, network_info, block_device_info=None):
        pass
    

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None):
        #XXX
        import pdb
        pdb.set_trace()
        vca = self.vcloud_managers.get(self.vcloud_nodes[0].name)
        result = vca.login(token=vca.token, org=vca.org, org_url=vca.vcloud_session.org_url)
        if not result:
            LOG.error('login to vloud failed')

        the_vdc = vca.get_vdc(self.vcloud_nodes[0].vdc_name)
        the_vapp = vca.get_vapp(the_vdc, instance.uuid)
        if not the_vapp:
            LOG.error('the vapp %s do not exist' % instance.uuid )
            return
        
        result_ud = the_vapp.undeploy()
        if result_ud != False:
            LOG.info('waiting for stopping vapp %s' % instance.uuid)
            time.sleep(5)
 
        result_del = the_vapp.delete()
        while not result_del:
            LOG.info('waiting for stopping vapp %s' % instance.uuid)
            time.sleep(5)
            result_del = the_vapp.delete()      
      

#         key = instance['name']
#         if key in self.instances:
#             del self.instances[key]
#         else:
#             LOG.warning(_("Key '%(key)s' not in instances '%(inst)s'") %
#                         {'key': key,
#                          'inst': self.instances}, instance=instance)


    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None, destroy_vifs=True):
        pass

    def attach_volume(self, context, connection_info, instance, mountpoint,
                      disk_bus=None, device_type=None, encryption=None):
        """Attach the disk to the instance at mountpoint using info."""
#         instance_name = instance['name']
#         if instance_name not in self._mounts:
#             self._mounts[instance_name] = {}
#         self._mounts[instance_name][mountpoint] = connection_info

    def detach_volume(self, connection_info, instance, mountpoint,
                      encryption=None):
        """Detach the disk attached to the instance."""
#         try:
#             del self._mounts[instance['name']][mountpoint]
#         except KeyError:
#             pass

    def swap_volume(self, old_connection_info, new_connection_info,
                    instance, mountpoint, resize_to):
        """Replace the disk attached to the instance."""
#         instance_name = instance['name']
#         if instance_name not in self._mounts:
#             self._mounts[instance_name] = {}
#         self._mounts[instance_name][mountpoint] = new_connection_info

    def attach_interface(self, instance, image_meta, vif):
        pass
#         if vif['id'] in self._interfaces:
#             raise exception.InterfaceAttachFailed(
#                     instance_uuid=instance['uuid'])
#         self._interfaces[vif['id']] = vif

    def detach_interface(self, instance, vif):
        pass
#         try:
#             del self._interfaces[vif['id']]
#         except KeyError:
#             raise exception.InterfaceDetachFailed(
#                     instance_uuid=instance['uuid'])
  

    def get_info(self, instance):
        #XXX
        if instance['name'] not in self.instances:
            raise exception.InstanceNotFound(instance_id=instance['name'])
        i = self.instances[instance['name']]
        return {'state': power_state.NOSTATE,
                 'max_mem': 0,
                 'mem': 0,
                 'num_cpu': 2,
                 'cpu_time': 0}

    def get_diagnostics(self, instance_name):
        pass
#         return {'cpu0_time': 17300000000,
#                 'memory': 524288,
#                 'vda_errors': -1,
#                 'vda_read': 262144,
#                 'vda_read_req': 112,
#                 'vda_write': 5778432,
#                 'vda_write_req': 488,
#                 'vnet1_rx': 2070139,
#                 'vnet1_rx_drop': 0,
#                 'vnet1_rx_errors': 0,
#                 'vnet1_rx_packets': 26701,
#                 'vnet1_tx': 140208,
#                 'vnet1_tx_drop': 0,
#                 'vnet1_tx_errors': 0,
#                 'vnet1_tx_packets': 662,
#         }

    def get_instance_diagnostics(self, instance_name):
        pass
#         diags = diagnostics.Diagnostics(state='running', driver='fake',
#                 hypervisor_os='fake-os', uptime=46664, config_drive=True)
#         diags.add_cpu(time=17300000000)
#         diags.add_nic(mac_address='01:23:45:67:89:ab',
#                       rx_packets=26701,
#                       rx_octets=2070139,
#                       tx_octets=140208,
#                       tx_packets = 662)
#         diags.add_disk(id='fake-disk-id',
#                        read_bytes=262144,
#                        read_requests=112,
#                        write_bytes=5778432,
#                        write_requests=488)
#         diags.memory_details.maximum = 524288
#         return diags

    def get_all_bw_counters(self, instances):
        """Return bandwidth usage counters for each interface on each
           running VM.
        """
        bw = []
        return bw

    def get_all_volume_usage(self, context, compute_host_bdms):
        """Return usage info for volumes attached to vms on
           a given host.
        """
        volusage = []
        return volusage

    def get_host_cpu_stats(self):
        pass
#         stats = {'kernel': 5664160000000L,
#                 'idle': 1592705190000000L,
#                 'user': 26728850000000L,
#                 'iowait': 6121490000000L}
#         stats['frequency'] = 800
#         return stats

    def block_stats(self, instance_name, disk_id):
        pass

    def interface_stats(self, instance_name, iface_id):
        pass

    def get_console_output(self, context, instance):
        return 'FAKE CONSOLE OUTPUT\nANOTHER\nLAST LINE'

    def get_vnc_console(self, context, instance):
        pass
#         return ctype.ConsoleVNC(internal_access_path='FAKE',
#                                 host='fakevncconsole.com',
#                                 port=6969)

    def get_spice_console(self, context, instance):
        pass
#         return ctype.ConsoleSpice(internal_access_path='FAKE',
#                                   host='fakespiceconsole.com',
#                                   port=6969,
#                                   tlsPort=6970)

    def get_rdp_console(self, context, instance):
        pass


    def get_serial_console(self, context, instance):
        pass


    def get_console_pool_info(self, console_type):
        pass

    def refresh_security_group_rules(self, security_group_id):
        return True

    def refresh_security_group_members(self, security_group_id):
        return True

    def refresh_instance_security_rules(self, instance):
        return True

    def refresh_provider_fw_rules(self):
        pass


    def get_available_resource(self, nodename):
        #XXX
        return {'vcpus':32,
               'memory_mb':164403,
               'local_gb': 5585L,
               'vcpus_used': 0,
               'memory_mb_used': 69005,
               'local_gb_used': 3479L,
               'hypervisor_type': 'vcloud',
               'hypervisor_version': 5005000,
               'hypervisor_hostname': nodename,
               'cpu_info': '{"model": ["Intel(R) Xeon(R) CPU E5-2670 0 @ 2.60GHz"], "vendor": ["Huawei Technologies Co., Ltd."], "topology": {"cores": 16, "threads": 32}}',
               'supported_instances': jsonutils.dumps(
                   [["i686", "vmware", "hvm"], ["x86_64", "vmware", "hvm"]]),
               'numa_topology': None,
               }
        

    def ensure_filtering_rules_for_instance(self, instance_ref, network_info):
        return

    def get_instance_disk_info(self, instance_name, block_device_info=None):
        return

    def live_migration(self, context, instance_ref, dest,
                       post_method, recover_method, block_migration=False,
                       migrate_data=None):
        post_method(context, instance_ref, dest, block_migration,
                            migrate_data)
        return

    def check_can_live_migrate_destination_cleanup(self, ctxt,
                                                   dest_check_data):
        return

    def check_can_live_migrate_destination(self, ctxt, instance_ref,
                                           src_compute_info, dst_compute_info,
                                           block_migration=False,
                                           disk_over_commit=False):
        return {}

    def check_can_live_migrate_source(self, ctxt, instance_ref,
                                      dest_check_data):
        return

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance,
                         block_device_info=None, power_on=True):
        return

    def confirm_migration(self, migration, instance, network_info):
        return

    def pre_live_migration(self, context, instance_ref, block_device_info,
                           network_info, disk, migrate_data=None):
        return

    def unfilter_instance(self, instance_ref, network_info):
        return

    def test_remove_vm(self, instance_name):
        """Removes the named VM, as if it crashed. For testing."""
        self.instances.pop(instance_name)

    def get_host_stats(self, refresh=False):
        """Return fake Host Status of ram, disk, network."""
#         stats = []
#         for nodename in _FAKE_NODES:
#             host_status = self.host_status_base.copy()
#             host_status['hypervisor_hostname'] = nodename
#             host_status['host_hostname'] = nodename
#             host_status['host_name_label'] = nodename
#             stats.append(host_status)
#         if len(stats) == 0:
#             raise exception.NovaException("FakeDriver has no node")
#         elif len(stats) == 1:
#             return stats[0]
#         else:
#             return stats

    def host_power_action(self, host, action):
        """Reboots, shuts down or powers up the host."""
        return action

    def host_maintenance_mode(self, host, mode):
        """Start/Stop host maintenance window. On start, it triggers
        guest VMs evacuation.
        """
        if not mode:
            return 'off_maintenance'
        return 'on_maintenance'

    def set_host_enabled(self, host, enabled):
        """Sets the specified host's ability to accept new instances."""
        if enabled:
            return 'enabled'
        return 'disabled'

    def get_volume_connector(self, instance):
        return {'ip': '127.0.0.1', 'initiator': 'fake', 'host': 'fakehost'}

    def get_available_nodes(self, refresh=False):
        node_list = []
        for node in self.vcloud_nodes:
            node_list.append(node.name)
        return node_list

    def instance_on_disk(self, instance):
        return False


        

  
