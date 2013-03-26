# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 IBM
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
import hashlib
import os
import re
import time

from nova import exception as nova_exception
from nova import flags
from nova import utils

from nova.compute import power_state
from nova.openstack.common import log as logging
from nova.virt import images
from nova.virt.powervm import command
from nova.virt.powervm import common
from nova.virt.powervm import constants
from nova.virt.powervm import exception
from nova.virt.powervm import lpar as LPAR


LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS


def get_powervm_operator():
    if FLAGS.powervm_mgr_type == 'ivm':
        return IVMOperator(common.Connection(FLAGS.powervm_mgr,
                                             FLAGS.powervm_mgr_user,
                                             FLAGS.powervm_mgr_passwd))


class PowerVMOperator(object):
    """PowerVM main operator.

    The PowerVMOperator is intented to wrapper all operations
    from the driver and handle either IVM or HMC managed systems.
    """

    def __init__(self):
        self._operator = get_powervm_operator()
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

        state = constants.POWERVM_POWER_STATE[lpar_instance['state']]
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
            LOG.exception(_("LPAR instance '%s' not found") % instance_name)
            raise exception.PowerVMLPARInstanceNotFound(
                                                instance_name=instance_name)
        return lpar_instance

    def list_instances(self):
        """
        Return the names of all the instances known to the virtualization
        layer, as a list.
        """
        lpar_instances = self._operator.list_lpar_instances()
        # We filter out instances that haven't been created
        # via OpenStack. Notice that this is fragile and it can
        # be improved later.
        instances = [instance for instance in lpar_instances
                     if re.search(r'^instance-[0-9]{8}$', instance)]
        return instances

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
               'disk_available_least': data['disk_total']}
        return dic

    def get_host_stats(self, refresh=False):
        """Return currently known host stats"""
        if refresh:
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
        data['supported_instances'] = constants.POWERVM_SUPPORTED_INSTANCES
        data['extres'] = ''

        self._host_stats = data

    def spawn(self, context, instance, image_id):
        def _create_lpar_instance(instance):
            host_stats = self.get_host_stats(refresh=True)
            inst_name = instance['name']

            # CPU/Memory min and max can be configurable. Lets assume
            # some default values for now.

            # Memory
            mem = instance['memory_mb']
            if mem > host_stats['host_memory_free']:
                LOG.exception(_('Not enough free memory in the host'))
                raise exception.PowerVMInsufficientFreeMemory(
                                               instance_name=instance['name'])
            mem_min = min(mem, constants.POWERVM_MIN_MEM)
            mem_max = mem + constants.POWERVM_MAX_MEM

            # CPU
            cpus = instance['vcpus']
            avail_cpus = host_stats['vcpus'] - host_stats['vcpus_used']
            if cpus > avail_cpus:
                LOG.exception(_('Insufficient available CPU on PowerVM'))
                raise exception.PowerVMInsufficientCPU(
                                               instance_name=instance['name'])
            cpus_min = min(cpus, constants.POWERVM_MIN_CPUS)
            cpus_max = cpus + constants.POWERVM_MAX_CPUS
            cpus_units_min = decimal.Decimal(cpus_min) / decimal.Decimal(10)
            cpus_units = decimal.Decimal(cpus) / decimal.Decimal(10)

            try:
                # Network
                eth_id = self._operator.get_virtual_eth_adapter_id()

                # LPAR configuration data
                lpar_inst = LPAR.LPAR(
                                name=inst_name, lpar_env='aixlinux',
                                min_mem=mem_min, desired_mem=mem,
                                max_mem=mem_max, proc_mode='shared',
                                sharing_mode='uncap', min_procs=cpus_min,
                                desired_procs=cpus, max_procs=cpus_max,
                                min_proc_units=cpus_units_min,
                                desired_proc_units=cpus_units,
                                max_proc_units=cpus_max,
                                virtual_eth_adapters='4/0/%s//0/0' % eth_id)

                LOG.debug(_("Creating LPAR instance '%s'") % instance['name'])
                self._operator.create_lpar(lpar_inst)
            except nova_exception.ProcessExecutionError:
                LOG.exception(_("LPAR instance '%s' creation failed") %
                            instance['name'])
                raise exception.PowerVMLPARCreationFailed()

        def _create_image(context, instance, image_id):
            """Fetch image from glance and copy it to the remote system."""
            try:
                file_name = '.'.join([image_id, 'gz'])
                file_path = os.path.join(FLAGS.powervm_img_local_path,
                                         file_name)
                LOG.debug(_("Fetching image '%s' from glance") % image_id)
                images.fetch_to_raw(context, image_id, file_path,
                                    instance['user_id'],
                                    project_id=instance['project_id'])
                LOG.debug(_("Copying image '%s' to IVM") % file_path)
                remote_path = FLAGS.powervm_img_remote_path
                remote_file_name, size = self._operator.copy_image_file(
                                                        file_path, remote_path)
                # Logical volume
                LOG.debug(_("Creating logical volume"))
                lpar_id = self._operator.get_lpar(instance['name'])['lpar_id']
                vhost = self._operator.get_vhost_by_instance_id(lpar_id)
                disk_name = self._operator.create_logical_volume(size)
                self._operator.attach_disk_to_vhost(disk_name, vhost)
                LOG.debug(_("Copying image to the device '%s'") % disk_name)
                self._operator.copy_file_to_device(remote_file_name, disk_name)
            except Exception, e:
                LOG.exception(_("PowerVM image creation failed: %s") % str(e))
                raise exception.PowerVMImageCreationFailed()

        try:
            _create_lpar_instance(instance)
            _create_image(context, instance, image_id)
            LOG.debug(_("Activating the LPAR instance '%s'")
                      % instance['name'])
            self._operator.start_lpar(instance['name'])

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
            self._cleanup(instance['name'])

    def destroy(self, instance_name):
        """Destroy (shutdown and delete) the specified instance.

        :param instance_name: Instance name.
        """
        try:
            self._cleanup(instance_name)
        except exception.PowerVMLPARInstanceNotFound:
            LOG.warn(_("During destroy, LPAR instance '%s' was not found on "
                       "PowerVM system.") % instance_name)

    def _cleanup(self, instance_name):
        try:
            lpar_id = self._get_instance(instance_name)['lpar_id']
            vhost = self._operator.get_vhost_by_instance_id(lpar_id)
            disk_name = self._operator.get_disk_name_by_vhost(vhost)

            LOG.debug(_("Shutting down the instance '%s'") % instance_name)
            self._operator.stop_lpar(instance_name)

            if disk_name:
                LOG.debug(_("Removing the logical volume '%s'") % disk_name)
                self._operator.remove_logical_volume(disk_name)

            LOG.debug(_("Deleting the LPAR instance '%s'") % instance_name)
            self._operator.remove_lpar(instance_name)
        except Exception:
            LOG.exception(_("PowerVM instance cleanup failed"))
            raise exception.PowerVMLPARInstanceCleanupFailed(
                                                  instance_name=instance_name)

    def power_off(self, instance_name):
        self._operator.stop(instance_name)

    def power_on(self, instance_name):
        self._operator.start(instance_name)


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
        if self._connection is None:
            self._connection = common.ssh_connect(self.connection_data)

    def get_lpar(self, instance_name, resource_type='lpar'):
        """Return a LPAR object by its instance name.

        :param instance_name: LPAR instance name
        :param resource_type: the type of resources to list
        :returns: LPAR object
        """
        cmd = self.command.lssyscfg('-r %s --filter "lpar_names=%s"'
                                    % (resource_type, instance_name))
        output = self.run_command(cmd)
        if not output:
            return None
        lpar = LPAR.load_from_conf_data(output[0])
        return lpar

    def list_lpar_instances(self):
        """List all existent LPAR instances names.

        :returns: list -- list with instances names.
        """
        lpar_names = self.run_command(self.command.lssyscfg('-r lpar -F name'))
        if not lpar_names:
            return []
        return lpar_names

    def create_lpar(self, lpar):
        """Receives a LPAR data object and creates a LPAR instance.

        :param lpar: LPAR object
        """
        conf_data = lpar.to_string()
        self.run_command(self.command.mksyscfg('-r lpar -i "%s"' % conf_data))

    def start_lpar(self, instance_name):
        """Start a LPAR instance.

        :param instance_name: LPAR instance name
        """
        self.run_command(self.command.chsysstate('-r lpar -o on -n %s'
                                                 % instance_name))

    def stop_lpar(self, instance_name):
        """Stop a running LPAR.

        :param instance_name: LPAR instance name
        """
        cmd = self.command.chsysstate('-r lpar -o shutdown --immed -n %s'
                                      % instance_name)
        self.run_command(cmd)

    def remove_lpar(self, instance_name):
        """Removes a LPAR.

        :param instance_name: LPAR instance name
        """
        self.run_command(self.command.rmsyscfg('-r lpar -n %s'
                                               % instance_name))

    def get_vhost_by_instance_id(self, instance_id):
        """Return the vhost name by the instance id.

        :param instance_id: LPAR instance id
        :returns: string -- vhost name or None in case none is found
        """
        instance_hex_id = '%#010x' % int(instance_id)
        cmd = self.command.lsmap('-all -field clientid svsa -fmt :')
        output = self.run_command(cmd)
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
        output = self.run_command(cmd)
        sea = output[0]
        cmd = self.command.lsdev('-dev %s -attr pvid' % sea)
        output = self.run_command(cmd)
        # Returned output looks like this: ['value', '', '1']
        if output:
            return output[2]

        return None

    def get_disk_name_by_vhost(self, vhost):
        """Returns the disk name attached to a vhost.

        :param vhost: a vhost name
        :returns: string -- disk name
        """
        cmd = self.command.lsmap('-vadapter %s -field backing -fmt :'
                                 % vhost)
        output = self.run_command(cmd)
        if output:
            return output[0]

        return None

    def get_hostname(self):
        """Returns the managed system hostname.

        :returns: string -- hostname
        """
        output = self.run_command(self.command.hostname())
        return output[0]

    def remove_disk(self, disk_name):
        """Removes a disk.

        :param disk: a disk name
        """
        self.run_command(self.command.rmdev('-dev %s' % disk_name))

    def create_logical_volume(self, size):
        """Creates a logical volume with a minimum size.

        :param size: size of the logical volume in bytes
        :returns: string -- the name of the new logical volume.
        :raises: PowerVMNoSpaceLeftOnVolumeGroup
        """
        vgs = self.run_command(self.command.lsvg())
        cmd = self.command.lsvg('%s -field vgname freepps -fmt :'
                                    % ' '.join(vgs))
        output = self.run_command(cmd)
        found_vg = None

        # If it's not a multiple of 1MB we get the next
        # multiple and use it as the megabyte_size.
        megabyte = 1024 * 1024
        if (size % megabyte) != 0:
            megabyte_size = int(size / megabyte) + 1
        else:
            megabyte_size = size / megabyte

        # Search for a volume group with enough free space for
        # the new logical volume.
        for vg in output:
            # Returned output example: 'rootvg:396 (25344 megabytes)'
            match = re.search(r'^(\w+):\d+\s\((\d+).+$', vg)
            if match is None:
                continue
            vg_name, avail_size = match.groups()
            if megabyte_size <= int(avail_size):
                found_vg = vg_name
                break

        if not found_vg:
            LOG.exception(_('Could not create logical volume. '
                            'No space left on any volume group.'))
            raise exception.PowerVMNoSpaceLeftOnVolumeGroup()

        cmd = self.command.mklv('%s %sB' % (found_vg, size / 512))
        lv_name, = self.run_command(cmd)
        return lv_name

    def remove_logical_volume(self, lv_name):
        """Removes the lv and the connection between its associated vscsi.

        :param lv_name: a logical volume name
        """
        cmd = self.command.rmvdev('-vdev %s -rmlv' % lv_name)
        self.run_command(cmd)

    def copy_file_to_device(self, source_path, device):
        """Copy file to device.

        :param source_path: path to input source file
        :param device: output device name
        """
        cmd = 'dd if=%s of=/dev/%s bs=1024k' % (source_path, device)
        self.run_command_as_root(cmd)

    def copy_image_file(self, source_path, remote_path):
        """Copy file to VIOS, decompress it, and return its new size and name.

        :param source_path: source file path
        :param remote_path remote file path
        """
        # Calculate source image checksum
        hasher = hashlib.md5()
        block_size = 0x10000
        img_file = file(source_path, 'r')
        buf = img_file.read(block_size)
        while len(buf) > 0:
            hasher.update(buf)
            buf = img_file.read(block_size)
        source_cksum = hasher.hexdigest()

        comp_path = remote_path + os.path.basename(source_path)
        uncomp_path = comp_path.rstrip(".gz")
        final_path = "%s.%s" % (uncomp_path, source_cksum)

        # Check whether the uncompressed image is already on IVM
        output = self.run_command("ls %s" % final_path, check_exit_code=False)

        # If the image does not exist already
        if not len(output):
            # Copy file to IVM
            common.ftp_put_command(self.connection_data, source_path,
                                   remote_path)

            # Verify image file checksums match
            cmd = ("/usr/bin/csum -h MD5 %s |"
                   "/usr/bin/awk '{print $1}'" % comp_path)
            output = self.run_command_as_root(cmd)
            if not len(output):
                LOG.exception("Unable to get checksum")
                raise exception.PowerVMFileTransferFailed()
            if source_cksum != output[0]:
                LOG.exception("Image checksums do not match")
                raise exception.PowerVMFileTransferFailed()

            # Unzip the image
            cmd = "/usr/bin/gunzip %s" % comp_path
            output = self.run_command_as_root(cmd)

            # Remove existing image file
            cmd = "/usr/bin/rm -f %s.*" % uncomp_path
            output = self.run_command_as_root(cmd)

            # Rename unzipped image
            cmd = "/usr/bin/mv %s %s" % (uncomp_path, final_path)
            output = self.run_command_as_root(cmd)

            # Remove compressed image file
            cmd = "/usr/bin/rm -f %s" % comp_path
            output = self.run_command_as_root(cmd)

        # Calculate file size in multiples of 512 bytes
        output = self.run_command("ls -o %s|awk '{print $4}'"
                                  % final_path, check_exit_code=False)
        if len(output):
            size = int(output[0])
        else:
            LOG.exception("Uncompressed image file not found")
            raise exception.PowerVMFileTransferFailed()
        if (size % 512 != 0):
            size = (int(size / 512) + 1) * 512

        return final_path, size

    def run_cfg_dev(self, device_name):
        """Run cfgdev command for a specific device.

        :param device_name: device name the cfgdev command will run.
        """
        cmd = self.command.cfgdev('-dev %s' % device_name)
        self.run_command(cmd)

    def attach_disk_to_vhost(self, disk, vhost):
        """Attach disk name to a specific vhost.

        :param disk: the disk name
        :param vhost: the vhost name
        """
        cmd = self.command.mkvdev('-vdev %s -vadapter %s') % (disk, vhost)
        self.run_command(cmd)

    def get_memory_info(self):
        """Get memory info.

        :returns: tuple - memory info (total_mem, avail_mem)
        """
        cmd = self.command.lshwres(
            '-r mem --level sys -F configurable_sys_mem,curr_avail_sys_mem')
        output = self.run_command(cmd)
        total_mem, avail_mem = output[0].split(',')
        return {'total_mem': int(total_mem),
                'avail_mem': int(avail_mem)}

    def get_cpu_info(self):
        """Get CPU info.

        :returns: tuple - cpu info (total_procs, avail_procs)
        """
        cmd = self.command.lshwres(
            '-r proc --level sys -F '
            'configurable_sys_proc_units,curr_avail_sys_proc_units')
        output = self.run_command(cmd)
        total_procs, avail_procs = output[0].split(',')
        return {'total_procs': float(total_procs),
                'avail_procs': float(avail_procs)}

    def get_disk_info(self):
        """Get the disk usage information.

        :returns: tuple - disk info (disk_total, disk_used, disk_avail)
        """
        vgs = self.run_command(self.command.lsvg())
        (disk_total, disk_used, disk_avail) = [0, 0, 0]
        for vg in vgs:
            cmd = self.command.lsvg('%s -field totalpps usedpps freepps -fmt :'
                                    % vg)
            output = self.run_command(cmd)
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

    def run_command(self, cmd, check_exit_code=True):
        """Run a remote command using an active ssh connection.

        :param command: String with the command to run.
        """
        self._set_connection()
        stdout, stderr = utils.ssh_execute(self._connection, cmd,
                                           check_exit_code=check_exit_code)
        return stdout.strip().splitlines()

    def run_command_as_root(self, command, check_exit_code=True):
        """Run a remote command as root using an active ssh connection.

        :param command: List of commands.
        """
        self._set_connection()
        stdout, stderr = common.ssh_command_as_root(
            self._connection, command, check_exit_code=check_exit_code)
        return stdout.read().splitlines()


class IVMOperator(BaseOperator):
    """Integrated Virtualization Manager (IVM) Operator.

    Runs specific commands on an IVM managed system.
    """

    def __init__(self, ivm_connection):
        self.command = command.IVMCommand()
        BaseOperator.__init__(self, ivm_connection)
