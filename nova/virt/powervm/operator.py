# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 IBM Corp.
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

import decimal
import random
import re
import time

from eventlet import timeout as eventlet_timeout
from oslo.config import cfg

from nova.compute import power_state
from nova import exception as n_exc
from nova.openstack.common import excutils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import loopingcall
from nova.openstack.common import processutils
from nova.virt.powervm import blockdev
from nova.virt.powervm import command
from nova.virt.powervm import common
from nova.virt.powervm import constants
from nova.virt.powervm import exception
from nova.virt.powervm import lpar as LPAR

LOG = logging.getLogger(__name__)
CONF = cfg.CONF


def get_powervm_operator():
    if CONF.powervm_mgr_type == 'ivm':
        return IVMOperator(common.Connection(CONF.powervm_mgr,
                                             CONF.powervm_mgr_user,
                                             CONF.powervm_mgr_passwd))


def get_powervm_disk_adapter():
    return blockdev.PowerVMLocalVolumeAdapter(
            common.Connection(CONF.powervm_mgr,
                              CONF.powervm_mgr_user,
                              CONF.powervm_mgr_passwd))


class PowerVMOperator(object):
    """PowerVM main operator.

    The PowerVMOperator is intended to wrap all operations
    from the driver and handle either IVM or HMC managed systems.
    """

    def __init__(self):
        self._operator = get_powervm_operator()
        self._disk_adapter = get_powervm_disk_adapter()
        self._host_stats = {}
        self._update_host_stats()

    def get_info(self, instance_name):
        """Get the current status of an LPAR instance.

        Returns a dict containing:

        :state:           the running state, one of the power_state codes
        :max_mem:         (int) the maximum memory in KBytes allowed
        :mem:             (int) the memory in KBytes used by the domain
        :num_cpu:         (int) the number of virtual CPUs for the domain
        :cpu_time:        (int) the CPU time used in nanoseconds

        :raises: PowerVMLPARInstanceNotFound
        """
        lpar_instance = self._get_instance(instance_name)

        state = constants.POWERVM_POWER_STATE.get(
                lpar_instance['state'], power_state.NOSTATE)
        return {'state': state,
                'max_mem': lpar_instance['max_mem'],
                'mem': lpar_instance['desired_mem'],
                'num_cpu': lpar_instance['max_procs'],
                'cpu_time': lpar_instance['uptime']}

    def instance_exists(self, instance_name):
        lpar_instance = self._operator.get_lpar(instance_name)
        return True if lpar_instance else False

    def _get_instance(self, instance_name):
        """Check whether or not the LPAR instance exists and return it."""
        lpar_instance = self._operator.get_lpar(instance_name)

        if lpar_instance is None:
            LOG.error(_("LPAR instance '%s' not found") % instance_name)
            raise exception.PowerVMLPARInstanceNotFound(
                                                instance_name=instance_name)
        return lpar_instance

    def list_instances(self):
        """
        Return the names of all the instances known to the virtualization
        layer, as a list.
        """
        lpar_instances = self._operator.list_lpar_instances()
        return lpar_instances

    def get_available_resource(self):
        """Retrieve resource info.

        :returns: dictionary containing resource info
        """
        data = self.get_host_stats()
        # Memory data is in MB already.
        memory_mb_used = data['host_memory_total'] - data['host_memory_free']

        # Convert to GB
        local_gb = data['disk_total'] / 1024
        local_gb_used = data['disk_used'] / 1024

        dic = {'vcpus': data['vcpus'],
               'memory_mb': data['host_memory_total'],
               'local_gb': local_gb,
               'vcpus_used': data['vcpus_used'],
               'memory_mb_used': memory_mb_used,
               'local_gb_used': local_gb_used,
               'hypervisor_type': data['hypervisor_type'],
               'hypervisor_version': data['hypervisor_version'],
               'hypervisor_hostname': self._operator.get_hostname(),
               'cpu_info': ','.join(data['cpu_info']),
               'disk_available_least': data['disk_total'],
               'supported_instances': jsonutils.dumps(
                   data['supported_instances'])}
        return dic

    def get_host_stats(self, refresh=False):
        """Return currently known host stats."""
        if refresh or not self._host_stats:
            self._update_host_stats()
        return self._host_stats

    def _update_host_stats(self):
        memory_info = self._operator.get_memory_info()
        cpu_info = self._operator.get_cpu_info()

        # Note: disk avail information is not accurate. The value
        # is a sum of all Volume Groups and the result cannot
        # represent the real possibility. Example: consider two
        # VGs both 10G, the avail disk will be 20G however,
        # a 15G image does not fit in any VG. This can be improved
        # later on.
        disk_info = self._operator.get_disk_info()

        data = {}
        data['vcpus'] = cpu_info['total_procs']
        data['vcpus_used'] = cpu_info['total_procs'] - cpu_info['avail_procs']
        data['cpu_info'] = constants.POWERVM_CPU_INFO
        data['disk_total'] = disk_info['disk_total']
        data['disk_used'] = disk_info['disk_used']
        data['disk_available'] = disk_info['disk_avail']
        data['host_memory_total'] = memory_info['total_mem']
        data['host_memory_free'] = memory_info['avail_mem']
        data['hypervisor_type'] = constants.POWERVM_HYPERVISOR_TYPE
        data['hypervisor_version'] = constants.POWERVM_HYPERVISOR_VERSION
        data['hypervisor_hostname'] = self._operator.get_hostname()
        data['supported_instances'] = constants.POWERVM_SUPPORTED_INSTANCES
        data['extres'] = ''

        self._host_stats = data

    def get_host_uptime(self, host):
        """Returns the result of calling "uptime" on the target host."""
        return self._operator.get_host_uptime(host)

    def spawn(self, context, instance, image_id, network_info):
        def _create_image(context, instance, image_id):
            """Fetch image from glance and copy it to the remote system."""
            try:
                root_volume = self._disk_adapter.create_volume_from_image(
                        context, instance, image_id)

                self._disk_adapter.attach_volume_to_host(root_volume)

                lpar_id = self._operator.get_lpar(instance['name'])['lpar_id']
                vhost = self._operator.get_vhost_by_instance_id(lpar_id)
                self._operator.attach_disk_to_vhost(
                        root_volume['device_name'], vhost)
            except Exception as e:
                LOG.exception(_("PowerVM image creation failed: %s") % str(e))
                raise exception.PowerVMImageCreationFailed()

        spawn_start = time.time()

        try:
            try:
                host_stats = self.get_host_stats(refresh=True)
                lpar_inst = self._create_lpar_instance(instance,
                            network_info, host_stats)
                #TODO(mjfork) capture the error and handle the error when the
                #             MAC prefix already exists on the
                #             system (1 in 2^28)
                self._operator.create_lpar(lpar_inst)
                LOG.debug(_("Creating LPAR instance '%s'") % instance['name'])
            except processutils.ProcessExecutionError:
                LOG.exception(_("LPAR instance '%s' creation failed") %
                        instance['name'])
                raise exception.PowerVMLPARCreationFailed(
                    instance_name=instance['name'])

            _create_image(context, instance, image_id)
            LOG.debug(_("Activating the LPAR instance '%s'")
                      % instance['name'])
            self._operator.start_lpar(instance['name'])

            # TODO(mrodden): probably do this a better way
            #                that actually relies on the time module
            #                and nonblocking threading
            # Wait for boot
            timeout_count = range(10)
            while timeout_count:
                state = self.get_info(instance['name'])['state']
                if state == power_state.RUNNING:
                    LOG.info(_("Instance spawned successfully."),
                             instance=instance)
                    break
                timeout_count.pop()
                if len(timeout_count) == 0:
                    LOG.error(_("Instance '%s' failed to boot") %
                              instance['name'])
                    self._cleanup(instance['name'])
                    break
                time.sleep(1)

        except exception.PowerVMImageCreationFailed:
            with excutils.save_and_reraise_exception():
                # log errors in cleanup
                try:
                    self._cleanup(instance['name'])
                except Exception:
                    LOG.exception(_('Error while attempting to '
                                    'clean up failed instance launch.'))

        spawn_time = time.time() - spawn_start
        LOG.info(_("Instance spawned in %s seconds") % spawn_time,
                 instance=instance)

    def destroy(self, instance_name, destroy_disks=True):
        """Destroy (shutdown and delete) the specified instance.

        :param instance_name: Instance name.
        """
        try:
            self._cleanup(instance_name, destroy_disks)
        except exception.PowerVMLPARInstanceNotFound:
            LOG.warn(_("During destroy, LPAR instance '%s' was not found on "
                       "PowerVM system.") % instance_name)

    def capture_image(self, context, instance, image_id, image_meta,
                      update_task_state):
        """Capture the root disk for a snapshot

        :param context: nova context for this operation
        :param instance: instance information to capture the image from
        :param image_id: uuid of pre-created snapshot image
        :param image_meta: metadata to upload with captured image
        :param update_task_state: Function reference that allows for updates
                                  to the instance task state.
        """
        lpar = self._operator.get_lpar(instance['name'])
        previous_state = lpar['state']

        # stop the instance if it is running
        if previous_state == 'Running':
            LOG.debug(_("Stopping instance %s for snapshot.") %
                      instance['name'])
            # wait up to 2 minutes for shutdown
            self.power_off(instance['name'], timeout=120)

        # get disk_name
        vhost = self._operator.get_vhost_by_instance_id(lpar['lpar_id'])
        disk_name = self._operator.get_disk_name_by_vhost(vhost)

        # do capture and upload
        self._disk_adapter.create_image_from_volume(
                disk_name, context, image_id, image_meta, update_task_state)

        # restart instance if it was running before
        if previous_state == 'Running':
            self.power_on(instance['name'])

    def _cleanup(self, instance_name, destroy_disks=True):
        lpar_id = self._get_instance(instance_name)['lpar_id']
        try:
            vhost = self._operator.get_vhost_by_instance_id(lpar_id)
            disk_name = self._operator.get_disk_name_by_vhost(vhost)

            LOG.debug(_("Shutting down the instance '%s'") % instance_name)
            self._operator.stop_lpar(instance_name)

            #dperaza: LPAR should be deleted first so that vhost is
            #cleanly removed and detached from disk device.
            LOG.debug(_("Deleting the LPAR instance '%s'") % instance_name)
            self._operator.remove_lpar(instance_name)

            if disk_name and destroy_disks:
                # TODO(mrodden): we should also detach from the instance
                # before we start deleting things...
                volume_info = {'device_name': disk_name}
                #Volume info dictionary might need more info that is lost when
                #volume is detached from host so that it can be deleted
                self._disk_adapter.detach_volume_from_host(volume_info)
                self._disk_adapter.delete_volume(volume_info)
        except Exception:
            LOG.exception(_("PowerVM instance cleanup failed"))
            raise exception.PowerVMLPARInstanceCleanupFailed(
                                                  instance_name=instance_name)

    def power_off(self, instance_name,
                  timeout=constants.POWERVM_LPAR_OPERATION_TIMEOUT):
        self._operator.stop_lpar(instance_name, timeout)

    def power_on(self, instance_name):
        self._operator.start_lpar(instance_name)

    def macs_for_instance(self, instance):
        return self._operator.macs_for_instance(instance)

    def _create_lpar_instance(self, instance, network_info, host_stats=None):
        inst_name = instance['name']

        # CPU/Memory min and max can be configurable. Lets assume
        # some default values for now.

        # Memory
        mem = instance['memory_mb']
        if host_stats and mem > host_stats['host_memory_free']:
            LOG.error(_('Not enough free memory in the host'))
            raise exception.PowerVMInsufficientFreeMemory(
                                           instance_name=instance['name'])
        mem_min = min(mem, constants.POWERVM_MIN_MEM)
        mem_max = mem + constants.POWERVM_MAX_MEM

        # CPU
        cpus = instance['vcpus']
        if host_stats:
            avail_cpus = host_stats['vcpus'] - host_stats['vcpus_used']
            if cpus > avail_cpus:
                LOG.error(_('Insufficient available CPU on PowerVM'))
                raise exception.PowerVMInsufficientCPU(
                                           instance_name=instance['name'])
        cpus_min = min(cpus, constants.POWERVM_MIN_CPUS)
        cpus_max = cpus + constants.POWERVM_MAX_CPUS
        cpus_units_min = decimal.Decimal(cpus_min) / decimal.Decimal(10)
        cpus_units = decimal.Decimal(cpus) / decimal.Decimal(10)

        # Network
        # To ensure the MAC address on the guest matches the
        # generated value, pull the first 10 characters off the
        # MAC address for the mac_base_value parameter and then
        # get the integer value of the final 2 characters as the
        # slot_id parameter
        mac = network_info[0]['address']
        mac_base_value = (mac[:-2]).replace(':', '')
        eth_id = self._operator.get_virtual_eth_adapter_id()
        slot_id = int(mac[-2:], 16)
        virtual_eth_adapters = ('%(slot_id)s/0/%(eth_id)s//0/0' %
                                {'slot_id': slot_id, 'eth_id': eth_id})

        # LPAR configuration data
        # max_virtual_slots is hardcoded to 64 since we generate a MAC
        # address that must be placed in slots 32 - 64
        lpar_inst = LPAR.LPAR(
                        name=inst_name, lpar_env='aixlinux',
                        min_mem=mem_min, desired_mem=mem,
                        max_mem=mem_max, proc_mode='shared',
                        sharing_mode='uncap', min_procs=cpus_min,
                        desired_procs=cpus, max_procs=cpus_max,
                        min_proc_units=cpus_units_min,
                        desired_proc_units=cpus_units,
                        max_proc_units=cpus_max,
                        virtual_eth_mac_base_value=mac_base_value,
                        max_virtual_slots=64,
                        virtual_eth_adapters=virtual_eth_adapters)
        return lpar_inst

    def _check_host_resources(self, instance, vcpus, mem, host_stats):
        """Checks resources on host for resize, migrate, and spawn
        :param vcpus: CPUs to be used
        :param mem: memory requested by instance
        :param disk: size of disk to be expanded or created
        """
        if mem > host_stats['host_memory_free']:
            LOG.exception(_('Not enough free memory in the host'))
            raise exception.PowerVMInsufficientFreeMemory(
                                           instance_name=instance['name'])

        avail_cpus = host_stats['vcpus'] - host_stats['vcpus_used']
        if vcpus > avail_cpus:
            LOG.exception(_('Insufficient available CPU on PowerVM'))
            raise exception.PowerVMInsufficientCPU(
                                           instance_name=instance['name'])

    def migrate_disk(self, device_name, src_host, dest, image_path,
            instance_name=None):
        """Migrates SVC or Logical Volume based disks

        :param device_name: disk device name in /dev/
        :param dest: IP or DNS name of destination host/VIOS
        :param image_path: path on source and destination to directory
                           for storing image files
        :param instance_name: name of instance being migrated
        :returns: disk_info dictionary object describing root volume
                  information used for locating/mounting the volume
        """
        dest_file_path = self._disk_adapter.migrate_volume(
                device_name, src_host, dest, image_path, instance_name)
        disk_info = {}
        disk_info['root_disk_file'] = dest_file_path
        return disk_info

    def deploy_from_migrated_file(self, lpar, file_path, size,
                                  power_on=True):
        """Deploy the logical volume and attach to new lpar.

        :param lpar: lar instance
        :param file_path: logical volume path
        :param size: new size of the logical volume
        """
        need_decompress = file_path.endswith('.gz')

        try:
            # deploy lpar from file
            self._deploy_from_vios_file(lpar, file_path, size,
                                        decompress=need_decompress,
                                        power_on=power_on)
        finally:
            # cleanup migrated file
            self._operator._remove_file(file_path)

    def _deploy_from_vios_file(self, lpar, file_path, size,
                               decompress=True, power_on=True):
        self._operator.create_lpar(lpar)
        lpar = self._operator.get_lpar(lpar['name'])
        instance_id = lpar['lpar_id']
        vhost = self._operator.get_vhost_by_instance_id(instance_id)

        # Create logical volume on IVM
        diskName = self._disk_adapter._create_logical_volume(size)
        # Attach the disk to LPAR
        self._operator.attach_disk_to_vhost(diskName, vhost)

        # Copy file to device
        self._disk_adapter._copy_file_to_device(file_path, diskName,
                                                decompress)

        if power_on:
            self._operator.start_lpar(lpar['name'])


class BaseOperator(object):
    """Base operator for IVM and HMC managed systems."""

    def __init__(self, connection):
        """Constructor.

        :param connection: common.Connection object with the
                           information to connect to the remote
                           ssh.
        """
        self._connection = None
        self.connection_data = connection

    def _set_connection(self):
        # create a new connection or verify an existing connection
        # and re-establish if the existing connection is dead
        self._connection = common.check_connection(self._connection,
                                                   self.connection_data)

    def _poll_for_lpar_status(self, instance_name, status, operation,
                            timeout=constants.POWERVM_LPAR_OPERATION_TIMEOUT):
        """Polls until the LPAR with the given name reaches the given status.

        :param instance_name: LPAR instance name
        :param status: Poll until the given LPAR status is reached
        :param operation: The operation being performed, e.g. 'stop_lpar'
        :param timeout: The number of seconds to wait.
        :raises: PowerVMLPARInstanceNotFound
        :raises: PowerVMLPAROperationTimeout
        :raises: InvalidParameterValue
        """
        # make sure it's a valid status
        if (status == constants.POWERVM_NOSTATE or
                not status in constants.POWERVM_POWER_STATE):
            msg = _("Invalid LPAR state: %s") % status
            raise n_exc.InvalidParameterValue(err=msg)

        # raise the given timeout exception if the loop call doesn't complete
        # in the specified timeout
        timeout_exception = exception.PowerVMLPAROperationTimeout(
                                                operation=operation,
                                                instance_name=instance_name)
        with eventlet_timeout.Timeout(timeout, timeout_exception):
            def _wait_for_lpar_status(instance_name, status):
                """Called at an interval until the status is reached."""
                lpar_obj = self.get_lpar(instance_name)
                if lpar_obj['state'] == status:
                    raise loopingcall.LoopingCallDone()

            timer = loopingcall.FixedIntervalLoopingCall(_wait_for_lpar_status,
                                                         instance_name, status)
            timer.start(interval=1).wait()

    def get_lpar(self, instance_name, resource_type='lpar'):
        """Return a LPAR object by its instance name.

        :param instance_name: LPAR instance name
        :param resource_type: the type of resources to list
        :returns: LPAR object
        """
        cmd = self.command.lssyscfg('-r %s --filter "lpar_names=%s"'
                                    % (resource_type, instance_name))
        output = self.run_vios_command(cmd)
        if not output:
            return None
        lpar = LPAR.load_from_conf_data(output[0])
        return lpar

    def list_lpar_instances(self):
        """List all existent LPAR instances names.

        :returns: list -- list with instances names.
        """
        lpar_names = self.run_vios_command(self.command.lssyscfg(
                    '-r lpar -F name'))
        if not lpar_names:
            return []
        return lpar_names

    def create_lpar(self, lpar):
        """Receives a LPAR data object and creates a LPAR instance.

        :param lpar: LPAR object
        """
        conf_data = lpar.to_string()
        self.run_vios_command(self.command.mksyscfg('-r lpar -i "%s"' %
                                                    conf_data))

    def start_lpar(self, instance_name,
                   timeout=constants.POWERVM_LPAR_OPERATION_TIMEOUT):
        """Start a LPAR instance.

        :param instance_name: LPAR instance name
        :param timeout: value in seconds for specifying
                        how long to wait for the LPAR to start
        """
        self.run_vios_command(self.command.chsysstate('-r lpar -o on -n %s'
                                                 % instance_name))
        # poll instance until running or raise exception
        self._poll_for_lpar_status(instance_name, constants.POWERVM_RUNNING,
                                   'start_lpar', timeout)

    def stop_lpar(self, instance_name,
                  timeout=constants.POWERVM_LPAR_OPERATION_TIMEOUT):
        """Stop a running LPAR.

        :param instance_name: LPAR instance name
        :param timeout: value in seconds for specifying
                        how long to wait for the LPAR to stop
        """
        cmd = self.command.chsysstate('-r lpar -o shutdown --immed -n %s' %
                                      instance_name)
        self.run_vios_command(cmd)

        # poll instance until stopped or raise exception
        self._poll_for_lpar_status(instance_name, constants.POWERVM_SHUTDOWN,
                                   'stop_lpar', timeout)

    def remove_lpar(self, instance_name):
        """Removes a LPAR.

        :param instance_name: LPAR instance name
        """
        self.run_vios_command(self.command.rmsyscfg('-r lpar -n %s'
                                               % instance_name))

    def get_vhost_by_instance_id(self, instance_id):
        """Return the vhost name by the instance id.

        :param instance_id: LPAR instance id
        :returns: string -- vhost name or None in case none is found
        """
        instance_hex_id = '%#010x' % int(instance_id)
        cmd = self.command.lsmap('-all -field clientid svsa -fmt :')
        output = self.run_vios_command(cmd)
        vhosts = dict(item.split(':') for item in list(output))

        if instance_hex_id in vhosts:
            return vhosts[instance_hex_id]

        return None

    def get_virtual_eth_adapter_id(self):
        """Virtual ethernet adapter id.

        Searches for the shared ethernet adapter and returns
        its id.

        :returns: id of the virtual ethernet adapter.
        """
        cmd = self.command.lsmap('-all -net -field sea -fmt :')
        output = self.run_vios_command(cmd)
        sea = output[0]
        cmd = self.command.lsdev('-dev %s -attr pvid' % sea)
        output = self.run_vios_command(cmd)
        # Returned output looks like this: ['value', '', '1']
        if output:
            return output[2]

        return None

    def get_hostname(self):
        """Returns the managed system hostname.

        :returns: string -- hostname
        """
        output = self.run_vios_command(self.command.hostname())
        hostname = output[0]
        if not hasattr(self, '_hostname'):
            self._hostname = hostname
        elif hostname != self._hostname:
            LOG.error(_('Hostname has changed from %(old)s to %(new)s. '
                        'A restart is required to take effect.'
                        ) % {'old': self._hostname, 'new': hostname})
        return self._hostname

    def get_disk_name_by_vhost(self, vhost):
        """Returns the disk name attached to a vhost.

        :param vhost: a vhost name
        :returns: string -- disk name
        """
        cmd = self.command.lsmap('-vadapter %s -field backing -fmt :' % vhost)
        output = self.run_vios_command(cmd)
        if output:
            return output[0]

        return None

    def attach_disk_to_vhost(self, disk, vhost):
        """Attach disk name to a specific vhost.

        :param disk: the disk name
        :param vhost: the vhost name
        """
        cmd = self.command.mkvdev('-vdev %s -vadapter %s') % (disk, vhost)
        self.run_vios_command(cmd)

    def get_memory_info(self):
        """Get memory info.

        :returns: tuple - memory info (total_mem, avail_mem)
        """
        cmd = self.command.lshwres(
            '-r mem --level sys -F configurable_sys_mem,curr_avail_sys_mem')
        output = self.run_vios_command(cmd)
        total_mem, avail_mem = output[0].split(',')
        return {'total_mem': int(total_mem),
                'avail_mem': int(avail_mem)}

    def get_host_uptime(self, host):
        """
        Get host uptime.
        :returns: string - amount of time since last system startup
        """
        # The output of the command is like this:
        # "02:54PM  up 24 days,  5:41, 1 user, load average: 0.06, 0.03, 0.02"
        cmd = self.command.sysstat('-short %s' % self.connection_data.username)
        return self.run_vios_command(cmd)[0]

    def get_cpu_info(self):
        """Get CPU info.

        :returns: tuple - cpu info (total_procs, avail_procs)
        """
        cmd = self.command.lshwres(
            '-r proc --level sys -F '
            'configurable_sys_proc_units,curr_avail_sys_proc_units')
        output = self.run_vios_command(cmd)
        total_procs, avail_procs = output[0].split(',')
        return {'total_procs': float(total_procs),
                'avail_procs': float(avail_procs)}

    def get_disk_info(self):
        """Get the disk usage information.

        :returns: tuple - disk info (disk_total, disk_used, disk_avail)
        """
        vgs = self.run_vios_command(self.command.lsvg())
        (disk_total, disk_used, disk_avail) = [0, 0, 0]
        for vg in vgs:
            cmd = self.command.lsvg('%s -field totalpps usedpps freepps -fmt :'
                                    % vg)
            output = self.run_vios_command(cmd)
            # Output example:
            # 1271 (10168 megabytes):0 (0 megabytes):1271 (10168 megabytes)
            (d_total, d_used, d_avail) = re.findall(r'(\d+) megabytes',
                                                    output[0])
            disk_total += int(d_total)
            disk_used += int(d_used)
            disk_avail += int(d_avail)

        return {'disk_total': disk_total,
                'disk_used': disk_used,
                'disk_avail': disk_avail}

    def run_vios_command(self, cmd, check_exit_code=True):
        """Run a remote command using an active ssh connection.

        :param command: String with the command to run.
        """
        self._set_connection()
        stdout, stderr = processutils.ssh_execute(
            self._connection, cmd, check_exit_code=check_exit_code)

        error_text = stderr.strip()
        if error_text:
            LOG.warn(_("Found error stream for command \"%(cmd)s\": "
                        "%(error_text)s"),
                      {'cmd': cmd, 'error_text': error_text})

        return stdout.strip().splitlines()

    def run_vios_command_as_root(self, command, check_exit_code=True):
        """Run a remote command as root using an active ssh connection.

        :param command: List of commands.
        """
        self._set_connection()
        stdout, stderr = common.ssh_command_as_root(
            self._connection, command, check_exit_code=check_exit_code)

        error_text = stderr.read()
        if error_text:
            LOG.warn(_("Found error stream for command \"%(command)s\":"
                        " %(error_text)s"),
                      {'command': command, 'error_text': error_text})

        return stdout.read().splitlines()

    def macs_for_instance(self, instance):
        pass

    def update_lpar(self, lpar_info):
        """Resizing an LPAR

        :param lpar_info: dictionary of LPAR information
        """
        configuration_data = ('name=%s,min_mem=%s,desired_mem=%s,'
                              'max_mem=%s,min_procs=%s,desired_procs=%s,'
                              'max_procs=%s,min_proc_units=%s,'
                              'desired_proc_units=%s,max_proc_units=%s' %
                              (lpar_info['name'], lpar_info['min_mem'],
                               lpar_info['desired_mem'],
                               lpar_info['max_mem'],
                               lpar_info['min_procs'],
                               lpar_info['desired_procs'],
                               lpar_info['max_procs'],
                               lpar_info['min_proc_units'],
                               lpar_info['desired_proc_units'],
                               lpar_info['max_proc_units']))

        self.run_vios_command(self.command.chsyscfg('-r prof -i "%s"' %
                                               configuration_data))

    def get_logical_vol_size(self, diskname):
        """Finds and calculates the logical volume size in GB

        :param diskname: name of the logical volume
        :returns: size of logical volume in GB
        """
        configuration_data = ("ioscli lslv %s -fmt : -field pps ppsize" %
                                diskname)
        output = self.run_vios_command(configuration_data)
        pps, ppsize = output[0].split(':')
        ppsize = re.findall(r'\d+', ppsize)
        ppsize = int(ppsize[0])
        pps = int(pps)
        lv_size = ((pps * ppsize) / 1024)

        return lv_size

    def rename_lpar(self, instance_name, new_name):
        """Rename LPAR given by instance_name to new_name

        Note: For IVM based deployments, the name is
              limited to 31 characters and will be trimmed
              to meet this requirement

        :param instance_name: name of LPAR to be renamed
        :param new_name: desired new name of LPAR
        :returns: new name of renamed LPAR trimmed to 31 characters
                  if necessary
        """

        # grab first 31 characters of new name
        new_name_trimmed = new_name[:31]

        cmd = ''.join(['chsyscfg -r lpar -i ',
                       '"',
                       'name=%s,' % instance_name,
                       'new_name=%s' % new_name_trimmed,
                       '"'])

        self.run_vios_command(cmd)

        return new_name_trimmed

    def _remove_file(self, file_path):
        """Removes a file on the VIOS partition

        :param file_path: absolute path to file to be removed
        """
        command = 'rm -f %s' % file_path
        self.run_vios_command_as_root(command)

    def set_lpar_mac_base_value(self, instance_name, mac):
        """Set LPAR's property virtual_eth_mac_base_value

        :param instance_name: name of the instance to be set
        :param mac: mac of virtual ethernet
        """
        # NOTE(ldbragst) We only use the base mac value because the last
        # byte is the slot id of the virtual NIC, which doesn't change.
        mac_base_value = mac[:-2].replace(':', '')
        cmd = ' '.join(['chsyscfg -r lpar -i',
                        '"name=%s,' % instance_name,
                        'virtual_eth_mac_base_value=%s"' % mac_base_value])
        self.run_vios_command(cmd)


class IVMOperator(BaseOperator):
    """Integrated Virtualization Manager (IVM) Operator.

    Runs specific commands on an IVM managed system.
    """

    def __init__(self, ivm_connection):
        self.command = command.IVMCommand()
        BaseOperator.__init__(self, ivm_connection)

    def macs_for_instance(self, instance):
        """Generates set of valid MAC addresses for an IVM instance."""
        # NOTE(vish): We would prefer to use 0xfe here to ensure that linux
        #             bridge mac addresses don't change, but it appears to
        #             conflict with libvirt, so we use the next highest octet
        #             that has the unicast and locally administered bits set
        #             properly: 0xfa.
        #             Discussion: https://bugs.launchpad.net/nova/+bug/921838
        # NOTE(mjfork): For IVM-based PowerVM, we cannot directly set a MAC
        #               address on an LPAR, but rather need to construct one
        #               that can be used.  Retain the 0xfa as noted above,
        #               but ensure the final 2 hex values represent a value
        #               between 32 and 64 so we can assign as the slot id on
        #               the system. For future reference, the last octect
        #               should not exceed FF (255) since it would spill over
        #               into the higher-order octect.
        #
        #               FA:xx:xx:xx:xx:[32-64]

        macs = set()
        mac_base = [0xfa,
               random.randint(0x00, 0xff),
               random.randint(0x00, 0xff),
               random.randint(0x00, 0xff),
               random.randint(0x00, 0xff),
               random.randint(0x00, 0x00)]
        for n in range(32, 64):
            mac_base[5] = n
            macs.add(':'.join(map(lambda x: "%02x" % x, mac_base)))

        return macs
