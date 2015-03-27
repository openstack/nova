# Copyright (c) 2010 Cloud.com, Inc
# Copyright (c) 2012 Cloudbase Solutions Srl
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
A Hyper-V Nova Compute driver.
"""

from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.virt import driver
from nova.virt.hyperv import hostops
from nova.virt.hyperv import livemigrationops
from nova.virt.hyperv import migrationops
from nova.virt.hyperv import rdpconsoleops
from nova.virt.hyperv import snapshotops
from nova.virt.hyperv import vmops
from nova.virt.hyperv import volumeops

LOG = logging.getLogger(__name__)


class HyperVDriver(driver.ComputeDriver):
    def __init__(self, virtapi):
        super(HyperVDriver, self).__init__(virtapi)

        self._hostops = hostops.HostOps()
        self._volumeops = volumeops.VolumeOps()
        self._vmops = vmops.VMOps()
        self._snapshotops = snapshotops.SnapshotOps()
        self._livemigrationops = livemigrationops.LiveMigrationOps()
        self._migrationops = migrationops.MigrationOps()
        self._rdpconsoleops = rdpconsoleops.RDPConsoleOps()

    def init_host(self, host):
        pass

    def list_instance_uuids(self):
        return self._vmops.list_instance_uuids()

    def list_instances(self):
        return self._vmops.list_instances()

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, network_info=None, block_device_info=None):
        self._vmops.spawn(context, instance, image_meta, injected_files,
                          admin_password, network_info, block_device_info)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        self._vmops.reboot(instance, network_info, reboot_type)

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True):
        self._vmops.destroy(instance, network_info, block_device_info,
                            destroy_disks)

    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True):
        """Cleanup after instance being destroyed by Hypervisor."""
        pass

    def get_info(self, instance):
        return self._vmops.get_info(instance)

    def attach_volume(self, context, connection_info, instance, mountpoint,
                      disk_bus=None, device_type=None, encryption=None):
        return self._volumeops.attach_volume(connection_info,
                                             instance['name'])

    def detach_volume(self, connection_info, instance, mountpoint,
                      encryption=None):
        return self._volumeops.detach_volume(connection_info,
                                             instance['name'])

    def get_volume_connector(self, instance):
        return self._volumeops.get_volume_connector(instance)

    def get_available_resource(self, nodename):
        return self._hostops.get_available_resource()

    def get_host_stats(self, refresh=False):
        return self._hostops.get_host_stats(refresh)

    def host_power_action(self, host, action):
        return self._hostops.host_power_action(host, action)

    def snapshot(self, context, instance, name, update_task_state):
        self._snapshotops.snapshot(context, instance, name, update_task_state)

    def pause(self, instance):
        self._vmops.pause(instance)

    def unpause(self, instance):
        self._vmops.unpause(instance)

    def suspend(self, instance):
        self._vmops.suspend(instance)

    def resume(self, context, instance, network_info, block_device_info=None):
        self._vmops.resume(instance)

    def power_off(self, instance):
        self._vmops.power_off(instance)

    def power_on(self, context, instance, network_info,
                 block_device_info=None):
        self._vmops.power_on(instance, block_device_info)

    def resume_state_on_host_boot(self, context, instance, network_info,
                                  block_device_info=None):
        """Resume guest state when a host is booted."""
        self._vmops.resume_state_on_host_boot(context, instance, network_info,
                                              block_device_info)

    def live_migration(self, context, instance_ref, dest, post_method,
                       recover_method, block_migration=False,
                       migrate_data=None):
        self._livemigrationops.live_migration(context, instance_ref, dest,
                                              post_method, recover_method,
                                              block_migration, migrate_data)

    def rollback_live_migration_at_destination(self, context, instance,
                                               network_info,
                                               block_device_info):
        self.destroy(context, instance, network_info, block_device_info)

    def pre_live_migration(self, context, instance, block_device_info,
                           network_info, disk, migrate_data=None):
        self._livemigrationops.pre_live_migration(context, instance,
                                                  block_device_info,
                                                  network_info)

    def post_live_migration_at_destination(self, ctxt, instance_ref,
                                           network_info,
                                           block_migr=False,
                                           block_device_info=None):
        self._livemigrationops.post_live_migration_at_destination(ctxt,
                                                                  instance_ref,
                                                                  network_info,
                                                                  block_migr)

    def check_can_live_migrate_destination(self, ctxt, instance_ref,
                                           src_compute_info, dst_compute_info,
                                           block_migration=False,
                                           disk_over_commit=False):
        return self._livemigrationops.check_can_live_migrate_destination(
            ctxt, instance_ref, src_compute_info, dst_compute_info,
            block_migration, disk_over_commit)

    def check_can_live_migrate_destination_cleanup(self, ctxt,
                                                   dest_check_data):
        self._livemigrationops.check_can_live_migrate_destination_cleanup(
            ctxt, dest_check_data)

    def check_can_live_migrate_source(self, ctxt, instance_ref,
                                      dest_check_data):
        return self._livemigrationops.check_can_live_migrate_source(
            ctxt, instance_ref, dest_check_data)

    def get_instance_disk_info(self, instance_name, block_device_info=None):
        pass

    def plug_vifs(self, instance, network_info):
        """Plug VIFs into networks."""
        msg = _("VIF plugging is not supported by the Hyper-V driver.")
        raise NotImplementedError(msg)

    def unplug_vifs(self, instance, network_info):
        """Unplug VIFs from networks."""
        msg = _("VIF unplugging is not supported by the Hyper-V driver.")
        raise NotImplementedError(msg)

    def ensure_filtering_rules_for_instance(self, instance_ref, network_info):
        LOG.debug(_("ensure_filtering_rules_for_instance called"),
                  instance=instance_ref)

    def unfilter_instance(self, instance, network_info):
        LOG.debug(_("unfilter_instance called"), instance=instance)

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   flavor, network_info,
                                   block_device_info=None):
        return self._migrationops.migrate_disk_and_power_off(context,
                                                             instance, dest,
                                                             flavor,
                                                             network_info,
                                                             block_device_info)

    def confirm_migration(self, migration, instance, network_info):
        self._migrationops.confirm_migration(migration, instance, network_info)

    def finish_revert_migration(self, context, instance, network_info,
                                block_device_info=None, power_on=True):
        self._migrationops.finish_revert_migration(context, instance,
                                                   network_info,
                                                   block_device_info, power_on)

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance=False,
                         block_device_info=None, power_on=True):
        self._migrationops.finish_migration(context, migration, instance,
                                            disk_info, network_info,
                                            image_meta, resize_instance,
                                            block_device_info, power_on)

    def get_host_ip_addr(self):
        return self._hostops.get_host_ip_addr()

    def get_host_uptime(self, host):
        return self._hostops.get_host_uptime()

    def get_rdp_console(self, context, instance):
        return self._rdpconsoleops.get_rdp_console(instance)
