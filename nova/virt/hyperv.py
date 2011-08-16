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
Uses Windows Management Instrumentation (WMI) calls to interact with Hyper-V
Hyper-V WMI usage:
    http://msdn.microsoft.com/en-us/library/cc723875%28v=VS.85%29.aspx
The Hyper-V object model briefly:
    The physical computer and its hosted virtual machines are each represented
    by the Msvm_ComputerSystem class.

    Each virtual machine is associated with a
    Msvm_VirtualSystemGlobalSettingData (vs_gs_data) instance and one or more
    Msvm_VirtualSystemSettingData (vmsetting) instances. For each vmsetting
    there is a series of Msvm_ResourceAllocationSettingData (rasd) objects.
    The rasd objects describe the settings for each device in a VM.
    Together, the vs_gs_data, vmsettings and rasds describe the configuration
    of the virtual machine.

    Creating new resources such as disks and nics involves cloning a default
    rasd object and appropriately modifying the clone and calling the
    AddVirtualSystemResources WMI method
    Changing resources such as memory uses the ModifyVirtualSystemResources
    WMI method

Using the Python WMI library:
    Tutorial:
        http://timgolden.me.uk/python/wmi/tutorial.html
    Hyper-V WMI objects can be retrieved simply by using the class name
    of the WMI object and optionally specifying a column to filter the
    result set. More complex filters can be formed using WQL (sql-like)
    queries.
    The parameters and return tuples of WMI method calls can gleaned by
    examining the doc string. For example:
    >>> vs_man_svc.ModifyVirtualSystemResources.__doc__
    ModifyVirtualSystemResources (ComputerSystem, ResourceSettingData[])
                 => (Job, ReturnValue)'
    When passing setting data (ResourceSettingData) to the WMI method,
    an XML representation of the data is passed in using GetText_(1).
    Available methods on a service can be determined using method.keys():
    >>> vs_man_svc.methods.keys()
    vmsettings and rasds for a vm can be retrieved using the 'associators'
    method with the appropriate return class.
    Long running WMI commands generally return a Job (an instance of
    Msvm_ConcreteJob) whose state can be polled to determine when it finishes

"""

import os
import time

from nova import exception
from nova import flags
from nova import log as logging
from nova.compute import power_state
from nova.virt import driver
from nova.virt import images

wmi = None


FLAGS = flags.FLAGS


LOG = logging.getLogger('nova.virt.hyperv')


HYPERV_POWER_STATE = {
    3: power_state.SHUTDOWN,
    2: power_state.RUNNING,
    32768: power_state.PAUSED,
}


REQ_POWER_STATE = {
    'Enabled': 2,
    'Disabled': 3,
    'Reboot': 10,
    'Reset': 11,
    'Paused': 32768,
    'Suspended': 32769,
}


WMI_JOB_STATUS_STARTED = 4096
WMI_JOB_STATE_RUNNING = 4
WMI_JOB_STATE_COMPLETED = 7


def get_connection(_):
    global wmi
    if wmi is None:
        wmi = __import__('wmi')
    return HyperVConnection()


class HyperVConnection(driver.ComputeDriver):
    def __init__(self):
        super(HyperVConnection, self).__init__()
        self._conn = wmi.WMI(moniker='//./root/virtualization')
        self._cim_conn = wmi.WMI(moniker='//./root/cimv2')

    def init_host(self, host):
        #FIXME(chiradeep): implement this
        LOG.debug(_('In init host'))
        pass

    def list_instances(self):
        """ Return the names of all the instances known to Hyper-V. """
        vms = [v.ElementName \
                for v in self._conn.Msvm_ComputerSystem(['ElementName'])]
        return vms

    def list_instances_detail(self):
        # TODO(justinsb): This is a terrible implementation (1+N)
        instance_infos = []
        for instance_name in self.list_instances():
            info = self.get_info(instance_name)

            state = info['state']

            instance_info = driver.InstanceInfo(instance_name, state)
            instance_infos.append(instance_info)

        return instance_infos

    def spawn(self, context, instance,
              network_info=None, block_device_info=None):
        """ Create a new VM and start it."""
        vm = self._lookup(instance.name)
        if vm is not None:
            raise exception.InstanceExists(name=instance.name)

        #Fetch the file, assume it is a VHD file.
        base_vhd_filename = os.path.join(FLAGS.instances_path,
                                         instance.name)
        vhdfile = "%s.vhd" % (base_vhd_filename)
        images.fetch(instance['image_ref'], vhdfile,
                     instance['user_id'], instance['project_id'])

        try:
            self._create_vm(instance)

            self._create_disk(instance['name'], vhdfile)

            mac_address = None
            if instance['mac_addresses']:
                mac_address = instance['mac_addresses'][0]['address']

            self._create_nic(instance['name'], mac_address)

            LOG.debug(_('Starting VM %s '), instance.name)
            self._set_vm_state(instance['name'], 'Enabled')
            LOG.info(_('Started VM %s '), instance.name)
        except Exception as exn:
            LOG.exception(_('spawn vm failed: %s'), exn)
            self.destroy(instance)

    def _create_vm(self, instance):
        """Create a VM but don't start it.  """
        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]

        vs_gs_data = self._conn.Msvm_VirtualSystemGlobalSettingData.new()
        vs_gs_data.ElementName = instance['name']
        (job, ret_val) = vs_man_svc.DefineVirtualSystem(
                [], None, vs_gs_data.GetText_(1))[1:]
        if ret_val == WMI_JOB_STATUS_STARTED:
            success = self._check_job_status(job)
        else:
            success = (ret_val == 0)

        if not success:
            raise Exception(_('Failed to create VM %s'), instance.name)

        LOG.debug(_('Created VM %s...'), instance.name)
        vm = self._conn.Msvm_ComputerSystem(ElementName=instance.name)[0]

        vmsettings = vm.associators(
                          wmi_result_class='Msvm_VirtualSystemSettingData')
        vmsetting = [s for s in vmsettings
                        if s.SettingType == 3][0]  # avoid snapshots
        memsetting = vmsetting.associators(
                           wmi_result_class='Msvm_MemorySettingData')[0]
        #No Dynamic Memory, so reservation, limit and quantity are identical.
        mem = long(str(instance['memory_mb']))
        memsetting.VirtualQuantity = mem
        memsetting.Reservation = mem
        memsetting.Limit = mem

        (job, ret_val) = vs_man_svc.ModifyVirtualSystemResources(
                vm.path_(), [memsetting.GetText_(1)])
        LOG.debug(_('Set memory for vm %s...'), instance.name)
        procsetting = vmsetting.associators(
                wmi_result_class='Msvm_ProcessorSettingData')[0]
        vcpus = long(instance['vcpus'])
        procsetting.VirtualQuantity = vcpus
        procsetting.Reservation = vcpus
        procsetting.Limit = 100000  # static assignment to 100%

        (job, ret_val) = vs_man_svc.ModifyVirtualSystemResources(
                vm.path_(), [procsetting.GetText_(1)])
        LOG.debug(_('Set vcpus for vm %s...'), instance.name)

    def _create_disk(self, vm_name, vhdfile):
        """Create a disk and attach it to the vm"""
        LOG.debug(_('Creating disk for %(vm_name)s by attaching'
                ' disk file %(vhdfile)s') % locals())
        #Find the IDE controller for the vm.
        vms = self._conn.MSVM_ComputerSystem(ElementName=vm_name)
        vm = vms[0]
        vmsettings = vm.associators(
                wmi_result_class='Msvm_VirtualSystemSettingData')
        rasds = vmsettings[0].associators(
                wmi_result_class='MSVM_ResourceAllocationSettingData')
        ctrller = [r for r in rasds
                   if r.ResourceSubType == 'Microsoft Emulated IDE Controller'\
                   and r.Address == "0"]
        #Find the default disk drive object for the vm and clone it.
        diskdflt = self._conn.query(
                "SELECT * FROM Msvm_ResourceAllocationSettingData \
                WHERE ResourceSubType LIKE 'Microsoft Synthetic Disk Drive'\
                AND InstanceID LIKE '%Default%'")[0]
        diskdrive = self._clone_wmi_obj(
                'Msvm_ResourceAllocationSettingData', diskdflt)
        #Set the IDE ctrller as parent.
        diskdrive.Parent = ctrller[0].path_()
        diskdrive.Address = 0
        #Add the cloned disk drive object to the vm.
        new_resources = self._add_virt_resource(diskdrive, vm)
        if new_resources is None:
            raise Exception(_('Failed to add diskdrive to VM %s'),
                                             vm_name)
        diskdrive_path = new_resources[0]
        LOG.debug(_('New disk drive path is %s'), diskdrive_path)
        #Find the default VHD disk object.
        vhddefault = self._conn.query(
                "SELECT * FROM Msvm_ResourceAllocationSettingData \
                 WHERE ResourceSubType LIKE 'Microsoft Virtual Hard Disk' AND \
                 InstanceID LIKE '%Default%' ")[0]

        #Clone the default and point it to the image file.
        vhddisk = self._clone_wmi_obj(
                'Msvm_ResourceAllocationSettingData', vhddefault)
        #Set the new drive as the parent.
        vhddisk.Parent = diskdrive_path
        vhddisk.Connection = [vhdfile]

        #Add the new vhd object as a virtual hard disk to the vm.
        new_resources = self._add_virt_resource(vhddisk, vm)
        if new_resources is None:
            raise Exception(_('Failed to add vhd file to VM %s'),
                                             vm_name)
        LOG.info(_('Created disk for %s'), vm_name)

    def _create_nic(self, vm_name, mac):
        """Create a (emulated) nic and attach it to the vm"""
        LOG.debug(_('Creating nic for %s '), vm_name)
        #Find the vswitch that is connected to the physical nic.
        vms = self._conn.Msvm_ComputerSystem(ElementName=vm_name)
        extswitch = self._find_external_network()
        vm = vms[0]
        switch_svc = self._conn.Msvm_VirtualSwitchManagementService()[0]
        #Find the default nic and clone it to create a new nic for the vm.
        #Use Msvm_SyntheticEthernetPortSettingData for Windows or Linux with
        #Linux Integration Components installed.
        emulatednics_data = self._conn.Msvm_EmulatedEthernetPortSettingData()
        default_nic_data = [n for n in emulatednics_data
                            if n.InstanceID.rfind('Default') > 0]
        new_nic_data = self._clone_wmi_obj(
                'Msvm_EmulatedEthernetPortSettingData',
                default_nic_data[0])
        #Create a port on the vswitch.
        (new_port, ret_val) = switch_svc.CreateSwitchPort(vm_name, vm_name,
                                            "", extswitch.path_())
        if ret_val != 0:
            LOG.error(_('Failed creating a port on the external vswitch'))
            raise Exception(_('Failed creating port for %s'),
                    vm_name)
        ext_path = extswitch.path_()
        LOG.debug(_("Created switch port %(vm_name)s on switch %(ext_path)s")
                % locals())
        #Connect the new nic to the new port.
        new_nic_data.Connection = [new_port]
        new_nic_data.ElementName = vm_name + ' nic'
        new_nic_data.Address = ''.join(mac.split(':'))
        new_nic_data.StaticMacAddress = 'TRUE'
        #Add the new nic to the vm.
        new_resources = self._add_virt_resource(new_nic_data, vm)
        if new_resources is None:
            raise Exception(_('Failed to add nic to VM %s'),
                    vm_name)
        LOG.info(_("Created nic for %s "), vm_name)

    def _add_virt_resource(self, res_setting_data, target_vm):
        """Add a new resource (disk/nic) to the VM"""
        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]
        (job, new_resources, ret_val) = vs_man_svc.\
                    AddVirtualSystemResources([res_setting_data.GetText_(1)],
                                                target_vm.path_())
        success = True
        if ret_val == WMI_JOB_STATUS_STARTED:
            success = self._check_job_status(job)
        else:
            success = (ret_val == 0)
        if success:
            return new_resources
        else:
            return None

    #TODO: use the reactor to poll instead of sleep
    def _check_job_status(self, jobpath):
        """Poll WMI job state for completion"""
        #Jobs have a path of the form:
        #\\WIN-P5IG7367DAG\root\virtualization:Msvm_ConcreteJob.InstanceID=
        #"8A496B9C-AF4D-4E98-BD3C-1128CD85320D"
        inst_id = jobpath.split('=')[1].strip('"')
        jobs = self._conn.Msvm_ConcreteJob(InstanceID=inst_id)
        if len(jobs) == 0:
            return False
        job = jobs[0]
        while job.JobState == WMI_JOB_STATE_RUNNING:
            time.sleep(0.1)
            job = self._conn.Msvm_ConcreteJob(InstanceID=inst_id)[0]
        if job.JobState != WMI_JOB_STATE_COMPLETED:
            LOG.debug(_("WMI job failed: %s"), job.ErrorSummaryDescription)
            return False
        desc = job.Description
        elap = job.ElapsedTime
        LOG.debug(_("WMI job succeeded: %(desc)s, Elapsed=%(elap)s ")
                % locals())
        return True

    def _find_external_network(self):
        """Find the vswitch that is connected to the physical nic.
           Assumes only one physical nic on the host
        """
        #If there are no physical nics connected to networks, return.
        bound = self._conn.Msvm_ExternalEthernetPort(IsBound='TRUE')
        if len(bound) == 0:
            return None
        return self._conn.Msvm_ExternalEthernetPort(IsBound='TRUE')[0]\
            .associators(wmi_result_class='Msvm_SwitchLANEndpoint')[0]\
            .associators(wmi_result_class='Msvm_SwitchPort')[0]\
            .associators(wmi_result_class='Msvm_VirtualSwitch')[0]

    def _clone_wmi_obj(self, wmi_class, wmi_obj):
        """Clone a WMI object"""
        cl = self._conn.__getattr__(wmi_class)  # get the class
        newinst = cl.new()
        #Copy the properties from the original.
        for prop in wmi_obj._properties:
            newinst.Properties_.Item(prop).Value = \
                    wmi_obj.Properties_.Item(prop).Value
        return newinst

    def reboot(self, instance, network_info):
        """Reboot the specified instance."""
        vm = self._lookup(instance.name)
        if vm is None:
            raise exception.InstanceNotFound(instance_id=instance.id)
        self._set_vm_state(instance.name, 'Reboot')

    def destroy(self, instance, network_info, cleanup=True):
        """Destroy the VM. Also destroy the associated VHD disk files"""
        LOG.debug(_("Got request to destroy vm %s"), instance.name)
        vm = self._lookup(instance.name)
        if vm is None:
            return
        vm = self._conn.Msvm_ComputerSystem(ElementName=instance.name)[0]
        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]
        #Stop the VM first.
        self._set_vm_state(instance.name, 'Disabled')
        vmsettings = vm.associators(
                         wmi_result_class='Msvm_VirtualSystemSettingData')
        rasds = vmsettings[0].associators(
                         wmi_result_class='MSVM_ResourceAllocationSettingData')
        disks = [r for r in rasds \
                    if r.ResourceSubType == 'Microsoft Virtual Hard Disk']
        diskfiles = []
        #Collect disk file information before destroying the VM.
        for disk in disks:
            diskfiles.extend([c for c in disk.Connection])
        #Nuke the VM. Does not destroy disks.
        (job, ret_val) = vs_man_svc.DestroyVirtualSystem(vm.path_())
        if ret_val == WMI_JOB_STATUS_STARTED:
            success = self._check_job_status(job)
        elif ret_val == 0:
            success = True
        if not success:
            raise Exception(_('Failed to destroy vm %s') % instance.name)
        #Delete associated vhd disk files.
        for disk in diskfiles:
            vhdfile = self._cim_conn.CIM_DataFile(Name=disk)
            for vf in vhdfile:
                vf.Delete()
                instance_name = instance.name
                LOG.debug(_("Del: disk %(vhdfile)s vm %(instance_name)s")
                        % locals())

    def get_info(self, instance_id):
        """Get information about the VM"""
        vm = self._lookup(instance_id)
        if vm is None:
            raise exception.InstanceNotFound(instance_id=instance_id)
        vm = self._conn.Msvm_ComputerSystem(ElementName=instance_id)[0]
        vs_man_svc = self._conn.Msvm_VirtualSystemManagementService()[0]
        vmsettings = vm.associators(
                       wmi_result_class='Msvm_VirtualSystemSettingData')
        settings_paths = [v.path_() for v in vmsettings]
        #See http://msdn.microsoft.com/en-us/library/cc160706%28VS.85%29.aspx
        summary_info = vs_man_svc.GetSummaryInformation(
                                       [4, 100, 103, 105], settings_paths)[1]
        info = summary_info[0]
        state = str(HYPERV_POWER_STATE[info.EnabledState])
        memusage = str(info.MemoryUsage)
        numprocs = str(info.NumberOfProcessors)
        uptime = str(info.UpTime)

        LOG.debug(_("Got Info for vm %(instance_id)s: state=%(state)s,"
                " mem=%(memusage)s, num_cpu=%(numprocs)s,"
                " cpu_time=%(uptime)s") % locals())

        return {'state': HYPERV_POWER_STATE[info.EnabledState],
                'max_mem': info.MemoryUsage,
                'mem': info.MemoryUsage,
                'num_cpu': info.NumberOfProcessors,
                'cpu_time': info.UpTime}

    def _lookup(self, i):
        vms = self._conn.Msvm_ComputerSystem(ElementName=i)
        n = len(vms)
        if n == 0:
            return None
        elif n > 1:
            raise Exception(_('duplicate name found: %s') % i)
        else:
            return vms[0].ElementName

    def _set_vm_state(self, vm_name, req_state):
        """Set the desired state of the VM"""
        vms = self._conn.Msvm_ComputerSystem(ElementName=vm_name)
        if len(vms) == 0:
            return False
        (job, ret_val) = vms[0].RequestStateChange(REQ_POWER_STATE[req_state])
        success = False
        if ret_val == WMI_JOB_STATUS_STARTED:
            success = self._check_job_status(job)
        elif ret_val == 0:
            success = True
        elif ret_val == 32775:
            #Invalid state for current operation. Typically means it is
            #already in the state requested
            success = True
        if success:
            LOG.info(_("Successfully changed vm state of %(vm_name)s"
                    " to %(req_state)s") % locals())
        else:
            msg = _("Failed to change vm state of %(vm_name)s"
                    " to %(req_state)s") % locals()
            LOG.error(msg)
            raise Exception(msg)

    def attach_volume(self, instance_name, device_path, mountpoint):
        vm = self._lookup(instance_name)
        if vm is None:
            raise exception.InstanceNotFound(instance_id=instance_name)

    def detach_volume(self, instance_name, mountpoint):
        vm = self._lookup(instance_name)
        if vm is None:
            raise exception.InstanceNotFound(instance_id=instance_name)

    def poll_rescued_instances(self, timeout):
        pass

    def update_available_resource(self, ctxt, host):
        """This method is supported only by libvirt."""
        return

    def update_host_status(self):
        """See xenapi_conn.py implementation."""
        pass

    def get_host_stats(self, refresh=False):
        """See xenapi_conn.py implementation."""
        pass

    def host_power_action(self, host, action):
        """Reboots, shuts down or powers up the host."""
        pass

    def set_host_enabled(self, host, enabled):
        """Sets the specified host's ability to accept new instances."""
        pass
