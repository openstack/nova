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

import socket
import time

from oslo.config import cfg

from nova.compute import flavors
from nova.image import glance
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.virt import driver
from nova.virt.powervm import exception
from nova.virt.powervm import operator

LOG = logging.getLogger(__name__)

powervm_opts = [
    cfg.StrOpt('powervm_mgr_type',
               default='ivm',
               help='PowerVM manager type (ivm, hmc)'),
    cfg.StrOpt('powervm_mgr',
               help='PowerVM manager host or ip'),
    cfg.StrOpt('powervm_mgr_user',
               help='PowerVM manager user name'),
    cfg.StrOpt('powervm_mgr_passwd',
               help='PowerVM manager user password',
               secret=True),
    cfg.StrOpt('powervm_img_remote_path',
               default='/home/padmin',
               help='PowerVM image remote path where images will be moved.'
               ' Make sure this path can fit your biggest image in glance'),
    cfg.StrOpt('powervm_img_local_path',
               default='/tmp',
               help='Local directory to download glance images to.'
               ' Make sure this path can fit your biggest image in glance')
    ]

CONF = cfg.CONF
CONF.register_opts(powervm_opts)


class PowerVMDriver(driver.ComputeDriver):

    """PowerVM Implementation of Compute Driver."""

    def __init__(self, virtapi):
        super(PowerVMDriver, self).__init__(virtapi)
        self._powervm = operator.PowerVMOperator()

    def init_host(self, host):
        """Initialize anything that is necessary for the driver to function,
        including catching up with currently running VM's on the given host.
        """
        pass

    def get_info(self, instance):
        """Get the current status of an instance."""
        return self._powervm.get_info(instance['name'])

    def get_num_instances(self):
        return len(self.list_instances())

    def instance_exists(self, instance_name):
        return self._powervm.instance_exists(instance_name)

    def list_instances(self):
        return self._powervm.list_instances()

    def get_host_stats(self, refresh=False):
        """Return currently known host stats."""
        return self._powervm.get_host_stats(refresh=refresh)

    def get_host_uptime(self, host):
        """Returns the result of calling "uptime" on the target host."""
        return self._powervm.get_host_uptime(host)

    def plug_vifs(self, instance, network_info):
        """Plug VIFs into networks."""
        LOG.debug(_('Network injection is not supported by the '
                    'PowerVM driver.'), instance)
        pass

    def macs_for_instance(self, instance):
        return self._powervm.macs_for_instance(instance)

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None):
        """Create a new instance/VM/domain on powerVM."""
        self._powervm.spawn(context, instance, image_meta['id'], network_info)

    def destroy(self, instance, network_info, block_device_info=None,
                destroy_disks=True):
        """Destroy (shutdown and delete) the specified instance."""
        self._powervm.destroy(instance['name'], destroy_disks)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        """Reboot the specified instance.

        :param instance: Instance object as returned by DB layer.
        :param network_info:
           :py:meth:`~nova.network.manager.NetworkManager.get_instance_nw_info`
        :param reboot_type: Either a HARD or SOFT reboot
        :param block_device_info: Info pertaining to attached volumes
        :param bad_volumes_callback: Function to handle any bad volumes
            encountered
        """
        if reboot_type == 'SOFT':
            LOG.debug(_('Soft reboot is not supported for PowerVM.'),
                      instance=instance)
            return

        self.power_off(instance)
        self.power_on(context, instance, network_info, block_device_info)

    def get_host_ip_addr(self):
        """Retrieves the IP address of the hypervisor host."""
        LOG.debug(_("In get_host_ip_addr"))
        # TODO(mrodden): use operator get_hostname instead
        hostname = CONF.powervm_mgr
        LOG.debug(_("Attempting to resolve %s") % hostname)
        ip_addr = socket.gethostbyname(hostname)
        LOG.debug(_("%(hostname)s was successfully resolved to %(ip_addr)s") %
                  {'hostname': hostname, 'ip_addr': ip_addr})
        return ip_addr

    def snapshot(self, context, instance, image_id, update_task_state):
        """Snapshots the specified instance.

        :param context: security context
        :param instance: Instance object as returned by DB layer.
        :param image_id: Reference to a pre-created image that will
                         hold the snapshot.
        :param update_task_state: Function reference that allows for updates
                                  to the instance task state.
        """
        snapshot_start = time.time()

        # get current image info
        glance_service, old_image_id = glance.get_remote_image_service(
                context, instance['image_ref'])
        image_meta = glance_service.show(context, old_image_id)
        img_props = image_meta['properties']

        # build updated snapshot metadata
        snapshot_meta = glance_service.show(context, image_id)
        new_snapshot_meta = {'is_public': False,
                             'name': snapshot_meta['name'],
                             'status': 'active',
                             'properties': {'image_location': 'snapshot',
                                            'image_state': 'available',
                                            'owner_id': instance['project_id']
                                           },
                             'disk_format': image_meta['disk_format'],
                             'container_format': image_meta['container_format']
                            }

        # disk capture and glance upload
        self._powervm.capture_image(context, instance, image_id,
                                    new_snapshot_meta, update_task_state)

        snapshot_time = time.time() - snapshot_start
        inst_name = instance['name']
        LOG.info(_("%(inst_name)s captured in %(snapshot_time)s seconds"),
                 {'inst_name': inst_name, 'snapshot_time': snapshot_time})

    def pause(self, instance):
        """Pause the specified instance."""
        msg = _("pause is not supported for PowerVM")
        raise NotImplementedError(msg)

    def unpause(self, instance):
        """Unpause paused VM instance."""
        msg = _("unpause is not supported for PowerVM")
        raise NotImplementedError(msg)

    def suspend(self, instance):
        """suspend the specified instance."""
        raise NotImplementedError(_("Suspend is not supported by the"
                                    "PowerVM driver."))

    def resume(self, instance, network_info, block_device_info=None):
        """resume the specified instance."""
        raise NotImplementedError(_("Resume is not supported by the"
                                    "PowerVM driver."))

    def power_off(self, instance):
        """Power off the specified instance."""
        self._powervm.power_off(instance['name'])

    def power_on(self, context, instance, network_info,
                 block_device_info=None):
        """Power on the specified instance."""
        self._powervm.power_on(instance['name'])

    def get_available_resource(self, nodename):
        """Retrieve resource info."""
        return self._powervm.get_available_resource()

    def host_power_action(self, host, action):
        """Reboots, shuts down or powers up the host."""
        raise NotImplementedError(_("Host power action is not supported by the"
                                    "PowerVM driver."))

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   instance_type, network_info,
                                   block_device_info=None):
        """Transfers the disk of a running instance in multiple phases, turning
           off the instance before the end.

        :returns: disk_info dictionary that is passed as the
                  disk_info parameter to finish_migration
                  on the destination nova-compute host
        """
        src_host = self.get_host_ip_addr()
        pvm_op = self._powervm._operator
        lpar_obj = pvm_op.get_lpar(instance['name'])
        vhost = pvm_op.get_vhost_by_instance_id(lpar_obj['lpar_id'])
        diskname = pvm_op.get_disk_name_by_vhost(vhost)

        self._powervm.power_off(instance['name'], timeout=120)
        # NOTE(ldbragst) Here we need to check if the resize or migrate is
        # happening on the same host. If yes, then we need to assign a temp
        # mac address to the source LPAR so we don't have a conflict when
        # another LPAR is booted with the same mac address as the
        # original LPAR
        if src_host == dest:
            macs = self.macs_for_instance(instance)
            temp_mac = macs.pop()
            self._powervm._operator.set_lpar_mac_base_value(instance['name'],
                                                            temp_mac)

        disk_info = self._powervm.migrate_disk(
                diskname, src_host, dest, CONF.powervm_img_remote_path,
                instance['name'])
        disk_info['old_lv_size'] = pvm_op.get_logical_vol_size(diskname)
        new_name = self._get_resize_name(instance['name'])
        pvm_op.rename_lpar(instance['name'], new_name)
        return disk_info

    def _get_resize_name(self, instance_name):
        """Rename the instance to be migrated to avoid naming conflicts

        :param instance_name: name of instance to be migrated
        :returns: the new instance name
        """
        name_tag = 'rsz_'

        # if the current name would overflow with new tag
        if ((len(instance_name) + len(name_tag)) > 31):
            # remove enough chars for the tag to fit
            num_chars = len(name_tag)
            old_name = instance_name[num_chars:]
        else:
            old_name = instance_name

        return ''.join([name_tag, old_name])

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance,
                         block_device_info=None, power_on=True):
        """Completes a resize, turning on the migrated instance

        :param network_info:
           :py:meth:`~nova.network.manager.NetworkManager.get_instance_nw_info`
        :param image_meta: image object returned by nova.image.glance that
                           defines the image from which this instance
                           was created
        """
        lpar_obj = self._powervm._create_lpar_instance(instance, network_info)

        instance_type = flavors.extract_flavor(instance)
        new_lv_size = instance_type['root_gb']
        old_lv_size = disk_info['old_lv_size']
        if 'root_disk_file' in disk_info:
            disk_size = max(int(new_lv_size), int(old_lv_size))
            disk_size_bytes = disk_size * 1024 * 1024 * 1024
            self._powervm.deploy_from_migrated_file(
                    lpar_obj, disk_info['root_disk_file'], disk_size_bytes,
                    power_on)
        else:
            # this shouldn't get hit unless someone forgot to handle
            # a certain migration type
            raise exception.PowerVMUnrecognizedRootDevice(disk_info=disk_info)

    def confirm_migration(self, migration, instance, network_info):
        """Confirms a resize, destroying the source VM."""

        new_name = self._get_resize_name(instance['name'])
        self._powervm.destroy(new_name)

    def finish_revert_migration(self, instance, network_info,
                                block_device_info=None, power_on=True):
        """Finish reverting a resize."""

        new_name = self._get_resize_name(instance['name'])

        # NOTE(ldbragst) In the case of a resize_revert on the same host
        # we reassign the original mac address, replacing the temp mac
        # on the old instance that will be started
        # NOTE(guochbo) We can't judge if a resize_revert on the same host
        # due to the instance on destination host has been destoryed.
        # Original mac address is always kept in network_info, we can
        # reassign the original mac address here without negative effects
        # even the old instance kept the original mac address
        if self.instance_exists(new_name):
            original_mac = network_info[0]['address']
            self._powervm._operator.set_lpar_mac_base_value(new_name,
                                                            original_mac)
        # Make sure we don't have a failed same-host migration still
        # hanging around
            if self.instance_exists(instance['name']):
                self._powervm.destroy(instance['name'])
            # undo instance rename and start
            self._powervm._operator.rename_lpar(new_name, instance['name'])

        if power_on:
            self._powervm.power_on(instance['name'])

    def add_to_aggregate(self, context, aggregate, host, **kwargs):
        """Add a compute host to an aggregate."""
        pass

    def remove_from_aggregate(self, context, aggregate, host, **kwargs):
        """Remove a compute host from an aggregate."""
        pass

    def undo_aggregate_operation(self, context, op, aggregate,
                                  host, set_error=True):
        """Undo for Resource Pools."""
        pass
