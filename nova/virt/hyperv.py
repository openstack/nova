# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2010 Cloud.com, Inc
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
A connection to Hyper-V .

"""

import os
import logging
import wmi
import time

from twisted.internet import defer

from nova import flags
from nova.auth.manager import AuthManager
from nova.compute import power_state
from nova.virt import images


FLAGS = flags.FLAGS


HYPERV_POWER_STATE = {
    3   : power_state.SHUTDOWN,
    2  : power_state.RUNNING,
    32768   : power_state.PAUSED,
    32768: power_state.PAUSED, # TODO
    3  : power_state.CRASHED
}

REQ_POWER_STATE = {
    'Enabled' : 2,
    'Disabled': 3,
    'Reboot' : 10,
    'Reset' : 11,
    'Paused' : 32768,
    'Suspended': 32769
}


def get_connection(_):
    return HyperVConnection()


class HyperVConnection(object):
    def __init__(self):
        self._conn = wmi.WMI(moniker = '//./root/virtualization')
        self._cim_conn = wmi.WMI(moniker = '//./root/cimv2')

    def list_instances(self):
        vms = [v.ElementName \
                for v in self._conn.Msvm_ComputerSystem(['ElementName'])]
        return vms

    @defer.inlineCallbacks
    def spawn(self, instance):
        vm = yield self._lookup(instance.name)
        if vm is not None:
            raise Exception('Attempted to create non-unique name %s' %
                            instance.name)
    
        user = AuthManager().get_user(instance['user_id'])
        project = AuthManager().get_project(instance['project_id'])
        vhdfile = os.path.join(FLAGS.instances_path, instance['str_id'])+".vhd"
        yield images.fetch(instance['image_id'], vhdfile, user, project)
        
        try:
            yield self._create_vm(instance)

            yield self._create_disk(instance['name'], vhdfile)
            yield self._create_nic(instance['name'], instance['mac_address'])
        
            logging.debug ('Starting VM %s ', instance.name)
            yield self._set_vm_state(instance['name'], 'Enabled')
            logging.info('Started VM %s ', instance.name)
        except Exception as exn:
            logging.error('spawn vm failed: %s', exn)
            self.destroy(instance)

    def _create_vm(self, instance):
        """Create a VM record.  """
        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]

        vs_gs_data = self._conn.Msvm_VirtualSystemGlobalSettingData.new()
        vs_gs_data.ElementName = instance['name']
        (job, ret_val) =  vs_man_svc.DefineVirtualSystem(
                                        [], None, vs_gs_data.GetText_(1))[1:]
        if (ret_val == 4096 ): #WMI job started
            success = self._check_job_status(job)
        else:
            success = (ret_val == 0)
        
        if not success:
            raise Exception('Failed to create VM %s', instance.name)
            
        logging.debug('Created VM %s...', instance.name)
        vm = self._conn.Msvm_ComputerSystem (ElementName=instance.name)[0]

        vmsettings = vm.associators(wmi_result_class=
                                    'Msvm_VirtualSystemSettingData')
        vmsetting = [s for s in vmsettings
                        if s.SettingType == 3][0] #avoid snapshots
        memsetting = vmsetting.associators(wmi_result_class=
                                           'Msvm_MemorySettingData')[0]
        #No Dynamic Memory
        mem = long(str(instance['memory_mb']))
        memsetting.VirtualQuantity = mem
        memsetting.Reservation = mem
        memsetting.Limit = mem

        (job, ret_val) = vs_man_svc.ModifyVirtualSystemResources(
                                        vm.path_(), [memsetting.GetText_(1)])
        
        logging.debug('Set memory for vm %s...', instance.name)
        procsetting = vmsetting.associators(wmi_result_class=
                                           'Msvm_ProcessorSettingData')[0]
        vcpus = long(str(instance['vcpus']))
        #vcpus = 1
        procsetting.VirtualQuantity = vcpus
        procsetting.Reservation = vcpus
        procsetting.Limit = vcpus

        (job, ret_val) = vs_man_svc.ModifyVirtualSystemResources(
                                        vm.path_(), [procsetting.GetText_(1)])
        
        logging.debug('Set vcpus for vm %s...', instance.name)
        
        
    def _create_disk(self, vm_name, vhdfile):
        """Create a disk and attach it to the vm"""
        logging.debug("Creating disk for %s by attaching disk file %s", \
                        vm_name, vhdfile)
        vms = self._conn.MSVM_ComputerSystem (ElementName=vm_name)
        vm = vms[0]
        vmsettings = vm.associators(
                        wmi_result_class='Msvm_VirtualSystemSettingData')
        rasds = vmsettings[0].associators(
                        wmi_result_class='MSVM_ResourceAllocationSettingData')
        ctrller = [r for r in rasds
                    if r.ResourceSubType == 'Microsoft Emulated IDE Controller'\
                                         and r.Address == "0" ]
        diskdflt = self._conn.query(
                    "SELECT * FROM Msvm_ResourceAllocationSettingData \
                    WHERE ResourceSubType LIKE 'Microsoft Synthetic Disk Drive'\
                    AND InstanceID LIKE '%Default%'")[0]
        diskdrive = self._clone_wmi_obj(
                    'Msvm_ResourceAllocationSettingData', diskdflt)
        diskdrive.Parent = ctrller[0].path_()
        diskdrive.Address = 0
        new_resources = self._add_virt_resource(diskdrive, vm)
        
        if new_resources is None:
            raise Exception('Failed to add diskdrive to VM %s', vm_name)
            
        diskdrive_path = new_resources[0]
        logging.debug("New disk drive path is " + diskdrive_path)
        vhddefault = self._conn.query(
                "SELECT * FROM Msvm_ResourceAllocationSettingData \
                 WHERE ResourceSubType LIKE 'Microsoft Virtual Hard Disk' AND \
                 InstanceID LIKE '%Default%' ")[0]

        vhddisk = self._clone_wmi_obj(
                'Msvm_ResourceAllocationSettingData', vhddefault)
        vhddisk.Parent = diskdrive_path
        vhddisk.Connection = [vhdfile]

        new_resources = self._add_virt_resource(vhddisk, vm)
        if new_resources is None:
            raise Exception('Failed to add vhd file to VM %s', vm_name)
        logging.info("Created disk for %s ", vm_name)
       
    
    def _create_nic(self, vm_name, mac):
        """Create a (emulated) nic and attach it to the vm"""
        logging.debug("Creating nic for %s ", vm_name)
        vms = self._conn.Msvm_ComputerSystem (ElementName=vm_name)
        extswitch = self._find_external_network()
        vm = vms[0]
        switch_svc = self._conn.Msvm_VirtualSwitchManagementService ()[0]
        #use Msvm_SyntheticEthernetPortSettingData for Windows VMs or Linux with
        #Linux Integration Components installed
        emulatednics_data = self._conn.Msvm_EmulatedEthernetPortSettingData()
        default_nic_data = [n for n in emulatednics_data
                            if n.InstanceID.rfind('Default') >0 ]
        new_nic_data = self._clone_wmi_obj(
                                      'Msvm_EmulatedEthernetPortSettingData',
                                      default_nic_data[0])
        
        (created_sw, ret_val) = switch_svc.CreateSwitchPort(vm_name, vm_name,
                                            "", extswitch.path_())
        if (ret_val != 0):
            logging.debug("Failed to create a new port on the external network")
            return
        logging.debug("Created switch port %s on switch %s",
                        vm_name, extswitch.path_())
        new_nic_data.Connection = [created_sw]
        new_nic_data.ElementName = vm_name + ' nic'
        new_nic_data.Address = ''.join(mac.split(':'))
        new_nic_data.StaticMacAddress = 'TRUE'
        new_resources = self._add_virt_resource(new_nic_data, vm)
        if new_resources is None:
            raise Exception('Failed to add nic to VM %s', vm_name)
        logging.info("Created nic for %s ", vm_name)

    
    def _add_virt_resource(self, res_setting_data, target_vm):
        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]
        (job, new_resources, return_val) = vs_man_svc.\
                    AddVirtualSystemResources([res_setting_data.GetText_(1)],
                                                target_vm.path_())
        success = True
        if (return_val == 4096 ): #WMI job started
            success = self._check_job_status(job)
        else:
            success = (return_val == 0)
        if success:    
            return new_resources
        else:
            return None

    #TODO: use the reactor to poll instead of sleep
    def _check_job_status(self, jobpath):
        inst_id = jobpath.split(':')[1].split('=')[1].strip('\"')
        jobs = self._conn.Msvm_ConcreteJob(InstanceID=inst_id)
        if (len(jobs) == 0):
            return False
        job = jobs[0]
        while job.JobState == 4: #job started
            time.sleep(0.1)
            job = self._conn.Msvm_ConcreteJob(InstanceID=inst_id)[0]
        
        if (job.JobState != 7): #job success
            logging.debug("WMI job failed: " + job.ErrorSummaryDescription)
            return False
        
        logging.debug("WMI job succeeded: " + job.Description + ",Elapsed = " \
                      + job.ElapsedTime)

        return True
        
    
        
    def _find_external_network(self):
        bound = self._conn.Msvm_ExternalEthernetPort(IsBound='TRUE')
        if (len(bound) == 0):
            return None
        
        return self._conn.Msvm_ExternalEthernetPort(IsBound='TRUE')[0]\
            .associators(wmi_result_class='Msvm_SwitchLANEndpoint')[0]\
            .associators(wmi_result_class='Msvm_SwitchPort')[0]\
            .associators(wmi_result_class='Msvm_VirtualSwitch')[0]   

    def _clone_wmi_obj(self, wmi_class, wmi_obj):
        cl = self._conn.__getattr__(wmi_class)
        newinst = cl.new()
        for prop in wmi_obj._properties:
            newinst.Properties_.Item(prop).Value =\
                    wmi_obj.Properties_.Item(prop).Value
        return newinst
    

    @defer.inlineCallbacks
    def reboot(self, instance):
        vm = yield self._lookup(instance.name)
        if vm is None:
            raise Exception('instance not present %s' % instance.name)
        self._set_vm_state(instance.name, 'Reboot')            
        

    @defer.inlineCallbacks
    def destroy(self, instance):
        logging.debug("Got request to destroy vm %s", instance.name)
        vm = yield self._lookup(instance.name)
        if vm is None:
            defer.returnValue(None)
        vm = self._conn.Msvm_ComputerSystem (ElementName=instance.name)[0]
        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]
        self._set_vm_state(instance.name, 'Disabled')
        vmsettings = vm.associators(wmi_result_class=
                                          'Msvm_VirtualSystemSettingData')
        rasds = vmsettings[0].associators(wmi_result_class=
                                          'MSVM_ResourceAllocationSettingData')
        disks = [r for r in rasds \
                    if r.ResourceSubType == 'Microsoft Virtual Hard Disk' ]
        diskfiles = []
        for disk in disks:
            diskfiles.extend([c for c in disk.Connection])
                
        (job, ret_val) = vs_man_svc.DestroyVirtualSystem(vm.path_())
        if (ret_val == 4096 ): #WMI job started
            success = self._check_job_status(job)
        elif (ret_val == 0):
            success = True
        if not success:
            raise Exception('Failed to destroy vm %s' % instance.name)
        for disk in diskfiles:
            vhdfile = self._cim_conn.CIM_DataFile(Name=disk)
            for vf in vhdfile:
                vf.Delete()
                logging.debug("Deleted disk %s vm %s", vhdfile, instance.name)
        
        
    
    def get_info(self, instance_id):
        vm = self._lookup(instance_id)
        if vm is None:
            raise Exception('instance not present %s' % instance_id)
        vm = self._conn.Msvm_ComputerSystem(ElementName=instance_id)[0]
        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]
        vmsettings = vm.associators(wmi_result_class=
                                        'Msvm_VirtualSystemSettingData')
        settings_paths = [ v.path_() for v in vmsettings]
        summary_info = vs_man_svc.GetSummaryInformation(
                                            [4,100,103,105], settings_paths)[1]
        info = summary_info[0]
        logging.debug("Got Info for vm %s: state=%s, mem=%s, num_cpu=%s, \
                    cpu_time=%s", instance_id,
                    str(HYPERV_POWER_STATE[info.EnabledState]),
                    str(info.MemoryUsage),
                    str(info.NumberOfProcessors),
                    str(info.UpTime))
                    
        return {'state': HYPERV_POWER_STATE[info.EnabledState],
                'max_mem': info.MemoryUsage,
                'mem': info.MemoryUsage,
                'num_cpu': info.NumberOfProcessors,
                'cpu_time': info.UpTime}
    

    def _lookup(self, i):
        vms = self._conn.Msvm_ComputerSystem (ElementName=i)
        n = len(vms) 
        if n == 0:
            return None
        elif n > 1:
            raise Exception('duplicate name found: %s' % i)
        else:
            return vms[0].ElementName

    def _set_vm_state(self, vm_name, req_state):
        vms = self._conn.Msvm_ComputerSystem (ElementName=vm_name)
        if len(vms) == 0:
            return False
        status = vms[0].RequestStateChange(REQ_POWER_STATE[req_state])
        job = status[0]
        return_val = status[1]
        if (return_val == 4096 ): #WMI job started
            success = self._check_job_status(job)
        elif (return_val == 0):
            success = True
        if success:
            logging.info("Successfully changed vm state of %s to %s",
                                vm_name, req_state)
            return True
        else:
            logging.debug("Failed to change vm state of %s to %s",
                                vm_name, req_state)
            return False
    
    
    def attach_volume(self, instance_name, device_path, mountpoint):
        vm =  self._lookup(instance_name)
        if vm is None:
            raise Exception('Attempted to attach volume to nonexistent %s vm' %
                            instance_name)

    def detach_volume(self, instance_name, mountpoint):
        vm =  self._lookup(instance_name)
        if vm is None:
            raise Exception('Attempted to detach volume from nonexistent %s ' %
                            instance_name)

