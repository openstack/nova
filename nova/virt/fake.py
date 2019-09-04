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
A fake (in-memory) hypervisor+api.

Allows nova testing w/o a hypervisor.  This module also documents the
semantics of real hypervisor connections.

"""

import collections
import contextlib
import time
import uuid

import fixtures
import os_resource_classes as orc
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import versionutils

from nova.compute import power_state
from nova.compute import task_states
from nova.compute import vm_states
import nova.conf
from nova.console import type as ctype
from nova import exception
from nova.objects import diagnostics as diagnostics_obj
from nova.objects import fields as obj_fields
from nova.objects import migrate_data
from nova.virt import driver
from nova.virt import hardware
from nova.virt.ironic import driver as ironic
from nova.virt import virtapi

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)


class FakeInstance(object):

    def __init__(self, name, state, uuid):
        self.name = name
        self.state = state
        self.uuid = uuid

    def __getitem__(self, key):
        return getattr(self, key)


class Resources(object):
    vcpus = 0
    memory_mb = 0
    local_gb = 0
    vcpus_used = 0
    memory_mb_used = 0
    local_gb_used = 0

    def __init__(self, vcpus=8, memory_mb=8000, local_gb=500):
        self.vcpus = vcpus
        self.memory_mb = memory_mb
        self.local_gb = local_gb

    def claim(self, vcpus=0, mem=0, disk=0):
        self.vcpus_used += vcpus
        self.memory_mb_used += mem
        self.local_gb_used += disk

    def release(self, vcpus=0, mem=0, disk=0):
        self.vcpus_used -= vcpus
        self.memory_mb_used -= mem
        self.local_gb_used -= disk

    def dump(self):
        return {
            'vcpus': self.vcpus,
            'memory_mb': self.memory_mb,
            'local_gb': self.local_gb,
            'vcpus_used': self.vcpus_used,
            'memory_mb_used': self.memory_mb_used,
            'local_gb_used': self.local_gb_used
        }


class FakeDriver(driver.ComputeDriver):
    # These must match the traits in
    # nova.tests.functional.integrated_helpers.ProviderUsageBaseTestCase
    capabilities = {
        "has_imagecache": True,
        "supports_evacuate": True,
        "supports_migrate_to_same_host": True,
        "supports_attach_interface": True,
        "supports_tagged_attach_interface": True,
        "supports_tagged_attach_volume": True,
        "supports_extend_volume": True,
        "supports_multiattach": True,
        "supports_trusted_certs": True,
        "supports_pcpus": False,

        # Supported image types
        "supports_image_type_raw": True,
        "supports_image_type_vhd": False,
        }

    # Since we don't have a real hypervisor, pretend we have lots of
    # disk and ram so this driver can be used to test large instances.
    vcpus = 1000
    memory_mb = 800000
    local_gb = 600000

    """Fake hypervisor driver."""

    def __init__(self, virtapi, read_only=False):
        super(FakeDriver, self).__init__(virtapi)
        self.instances = {}
        self.resources = Resources(
            vcpus=self.vcpus,
            memory_mb=self.memory_mb,
            local_gb=self.local_gb)
        self.host_status_base = {
            'hypervisor_type': 'fake',
            'hypervisor_version': versionutils.convert_version_to_int('1.0'),
            'hypervisor_hostname': CONF.host,
            'cpu_info': {},
            'disk_available_least': 0,
            'supported_instances': [(
                obj_fields.Architecture.X86_64,
                obj_fields.HVType.FAKE,
                obj_fields.VMMode.HVM)],
            'numa_topology': None,
          }
        self._mounts = {}
        self._interfaces = {}
        self.active_migrations = {}
        self._host = None
        self._nodes = None

    def init_host(self, host):
        self._host = host
        # NOTE(gibi): this is unnecessary complex and fragile but this is
        # how many current functional sample tests expect the node name.
        self._nodes = (['fake-mini'] if self._host == 'compute'
                       else [self._host])

    def _set_nodes(self, nodes):
        # NOTE(gibi): this is not part of the driver interface but used
        # by our tests to customize the discovered nodes by the fake
        # driver.
        self._nodes = nodes

    def list_instances(self):
        return [self.instances[uuid].name for uuid in self.instances.keys()]

    def list_instance_uuids(self):
        return list(self.instances.keys())

    def plug_vifs(self, instance, network_info):
        """Plug VIFs into networks."""
        pass

    def unplug_vifs(self, instance, network_info):
        """Unplug VIFs from networks."""
        pass

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, allocations, network_info=None,
              block_device_info=None, power_on=True):

        if network_info:
            for vif in network_info:
                # simulate a real driver triggering the async network
                # allocation as it might cause an error
                vif.fixed_ips()
                # store the vif as attached so we can allow detaching it later
                # with a detach_interface() call.
                self._interfaces[vif['id']] = vif

        uuid = instance.uuid
        state = power_state.RUNNING if power_on else power_state.SHUTDOWN
        flavor = instance.flavor
        self.resources.claim(
            vcpus=flavor.vcpus,
            mem=flavor.memory_mb,
            disk=flavor.root_gb)
        fake_instance = FakeInstance(instance.name, state, uuid)
        self.instances[uuid] = fake_instance

    def snapshot(self, context, instance, image_id, update_task_state):
        if instance.uuid not in self.instances:
            raise exception.InstanceNotRunning(instance_id=instance.uuid)
        update_task_state(task_state=task_states.IMAGE_UPLOADING)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None):
        pass

    def get_host_ip_addr(self):
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
        self.instances[instance.uuid].state = power_state.RUNNING

    def poll_rebooting_instances(self, timeout, instances):
        pass

    def migrate_disk_and_power_off(self, context, instance, dest,
                                   flavor, network_info,
                                   block_device_info=None,
                                   timeout=0, retry_interval=0):
        pass

    def finish_revert_migration(self, context, instance, network_info,
                                migration, block_device_info=None,
                                power_on=True):
        self.instances[instance.uuid] = FakeInstance(
            instance.name, power_state.RUNNING, instance.uuid)

    def post_live_migration_at_destination(self, context, instance,
                                           network_info,
                                           block_migration=False,
                                           block_device_info=None):
        pass

    def power_off(self, instance, timeout=0, retry_interval=0):
        if instance.uuid in self.instances:
            self.instances[instance.uuid].state = power_state.SHUTDOWN
        else:
            raise exception.InstanceNotFound(instance_id=instance.uuid)

    def power_on(self, context, instance, network_info,
                 block_device_info=None):
        if instance.uuid in self.instances:
            self.instances[instance.uuid].state = power_state.RUNNING
        else:
            raise exception.InstanceNotFound(instance_id=instance.uuid)

    def trigger_crash_dump(self, instance):
        pass

    def soft_delete(self, instance):
        pass

    def restore(self, instance):
        pass

    def pause(self, instance):
        pass

    def unpause(self, instance):
        pass

    def suspend(self, context, instance):
        pass

    def resume(self, context, instance, network_info, block_device_info=None):
        pass

    def destroy(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True):
        key = instance.uuid
        if key in self.instances:
            flavor = instance.flavor
            self.resources.release(
                vcpus=flavor.vcpus,
                mem=flavor.memory_mb,
                disk=flavor.root_gb)
            del self.instances[key]
        else:
            LOG.warning("Key '%(key)s' not in instances '%(inst)s'",
                        {'key': key,
                         'inst': self.instances}, instance=instance)

    def cleanup(self, context, instance, network_info, block_device_info=None,
                destroy_disks=True, migrate_data=None, destroy_vifs=True):
        pass

    def attach_volume(self, context, connection_info, instance, mountpoint,
                      disk_bus=None, device_type=None, encryption=None):
        """Attach the disk to the instance at mountpoint using info."""
        instance_name = instance.name
        if instance_name not in self._mounts:
            self._mounts[instance_name] = {}
        self._mounts[instance_name][mountpoint] = connection_info

    def detach_volume(self, context, connection_info, instance, mountpoint,
                      encryption=None):
        """Detach the disk attached to the instance."""
        try:
            del self._mounts[instance.name][mountpoint]
        except KeyError:
            pass

    def swap_volume(self, context, old_connection_info, new_connection_info,
                    instance, mountpoint, resize_to):
        """Replace the disk attached to the instance."""
        instance_name = instance.name
        if instance_name not in self._mounts:
            self._mounts[instance_name] = {}
        self._mounts[instance_name][mountpoint] = new_connection_info

    def extend_volume(self, connection_info, instance, requested_size):
        """Extend the disk attached to the instance."""
        pass

    def attach_interface(self, context, instance, image_meta, vif):
        if vif['id'] in self._interfaces:
            raise exception.InterfaceAttachFailed(
                    instance_uuid=instance.uuid)
        self._interfaces[vif['id']] = vif

    def detach_interface(self, context, instance, vif):
        try:
            del self._interfaces[vif['id']]
        except KeyError:
            raise exception.InterfaceDetachFailed(
                    instance_uuid=instance.uuid)

    def get_info(self, instance, use_cache=True):
        if instance.uuid not in self.instances:
            raise exception.InstanceNotFound(instance_id=instance.uuid)
        i = self.instances[instance.uuid]
        return hardware.InstanceInfo(state=i.state)

    def get_diagnostics(self, instance):
        return {'cpu0_time': 17300000000,
                'memory': 524288,
                'vda_errors': -1,
                'vda_read': 262144,
                'vda_read_req': 112,
                'vda_write': 5778432,
                'vda_write_req': 488,
                'vnet1_rx': 2070139,
                'vnet1_rx_drop': 0,
                'vnet1_rx_errors': 0,
                'vnet1_rx_packets': 26701,
                'vnet1_tx': 140208,
                'vnet1_tx_drop': 0,
                'vnet1_tx_errors': 0,
                'vnet1_tx_packets': 662,
        }

    def get_instance_diagnostics(self, instance):
        diags = diagnostics_obj.Diagnostics(
            state='running', driver='libvirt', hypervisor='kvm',
            hypervisor_os='ubuntu', uptime=46664, config_drive=True)
        diags.add_cpu(id=0, time=17300000000, utilisation=15)
        diags.add_nic(mac_address='01:23:45:67:89:ab',
                      rx_octets=2070139,
                      rx_errors=100,
                      rx_drop=200,
                      rx_packets=26701,
                      rx_rate=300,
                      tx_octets=140208,
                      tx_errors=400,
                      tx_drop=500,
                      tx_packets = 662,
                      tx_rate=600)
        diags.add_disk(read_bytes=262144,
                       read_requests=112,
                       write_bytes=5778432,
                       write_requests=488,
                       errors_count=1)
        diags.memory_details = diagnostics_obj.MemoryDiagnostics(
            maximum=524288, used=0)
        return diags

    def get_all_bw_counters(self, instances):
        """Return bandwidth usage counters for each interface on each
           running VM.
        """
        bw = []
        for instance in instances:
            bw.append({'uuid': instance.uuid,
                       'mac_address': 'fa:16:3e:4c:2c:30',
                       'bw_in': 0,
                       'bw_out': 0})
        return bw

    def get_all_volume_usage(self, context, compute_host_bdms):
        """Return usage info for volumes attached to vms on
           a given host.
        """
        volusage = []
        if compute_host_bdms:
            volusage = [{'volume': compute_host_bdms[0][
                                       'instance_bdms'][0]['volume_id'],
                         'instance': compute_host_bdms[0]['instance'],
                         'rd_bytes': 0,
                         'rd_req': 0,
                         'wr_bytes': 0,
                         'wr_req': 0}]

        return volusage

    def get_host_cpu_stats(self):
        stats = {'kernel': 5664160000000,
                'idle': 1592705190000000,
                'user': 26728850000000,
                'iowait': 6121490000000}
        stats['frequency'] = 800
        return stats

    def block_stats(self, instance, disk_id):
        return [0, 0, 0, 0, None]

    def get_console_output(self, context, instance):
        return 'FAKE CONSOLE OUTPUT\nANOTHER\nLAST LINE'

    def get_vnc_console(self, context, instance):
        return ctype.ConsoleVNC(internal_access_path='FAKE',
                                host='fakevncconsole.com',
                                port=6969)

    def get_spice_console(self, context, instance):
        return ctype.ConsoleSpice(internal_access_path='FAKE',
                                  host='fakespiceconsole.com',
                                  port=6969,
                                  tlsPort=6970)

    def get_rdp_console(self, context, instance):
        return ctype.ConsoleRDP(internal_access_path='FAKE',
                                host='fakerdpconsole.com',
                                port=6969)

    def get_serial_console(self, context, instance):
        return ctype.ConsoleSerial(internal_access_path='FAKE',
                                   host='fakerdpconsole.com',
                                   port=6969)

    def get_mks_console(self, context, instance):
        return ctype.ConsoleMKS(internal_access_path='FAKE',
                                host='fakemksconsole.com',
                                port=6969)

    def get_console_pool_info(self, console_type):
        return {'address': '127.0.0.1',
                'username': 'fakeuser',
                'password': 'fakepassword'}

    def refresh_security_group_rules(self, security_group_id):
        return True

    def refresh_instance_security_rules(self, instance):
        return True

    def get_available_resource(self, nodename):
        """Updates compute manager resource info on ComputeNode table.

           Since we don't have a real hypervisor, pretend we have lots of
           disk and ram.
        """
        cpu_info = collections.OrderedDict([
            ('arch', 'x86_64'),
            ('model', 'Nehalem'),
            ('vendor', 'Intel'),
            ('features', ['pge', 'clflush']),
            ('topology', {
                'cores': 1,
                'threads': 1,
                'sockets': 4,
                }),
            ])
        if nodename not in self._nodes:
            return {}

        host_status = self.host_status_base.copy()
        host_status.update(self.resources.dump())
        host_status['hypervisor_hostname'] = nodename
        host_status['host_hostname'] = nodename
        host_status['host_name_label'] = nodename
        host_status['cpu_info'] = jsonutils.dumps(cpu_info)
        return host_status

    def update_provider_tree(self, provider_tree, nodename, allocations=None):
        # NOTE(yikun): If the inv record does not exists, the allocation_ratio
        # will use the CONF.xxx_allocation_ratio value if xxx_allocation_ratio
        # is set, and fallback to use the initial_xxx_allocation_ratio
        # otherwise.
        inv = provider_tree.data(nodename).inventory
        ratios = self._get_allocation_ratios(inv)
        inventory = {
            'VCPU': {
                'total': self.vcpus,
                'min_unit': 1,
                'max_unit': self.vcpus,
                'step_size': 1,
                'allocation_ratio': ratios[orc.VCPU],
                'reserved': CONF.reserved_host_cpus,
            },
            'MEMORY_MB': {
                'total': self.memory_mb,
                'min_unit': 1,
                'max_unit': self.memory_mb,
                'step_size': 1,
                'allocation_ratio': ratios[orc.MEMORY_MB],
                'reserved': CONF.reserved_host_memory_mb,
            },
            'DISK_GB': {
                'total': self.local_gb,
                'min_unit': 1,
                'max_unit': self.local_gb,
                'step_size': 1,
                'allocation_ratio': ratios[orc.DISK_GB],
                'reserved': self._get_reserved_host_disk_gb_from_config(),
            },
        }
        provider_tree.update_inventory(nodename, inventory)

    def ensure_filtering_rules_for_instance(self, instance, network_info):
        return

    def get_instance_disk_info(self, instance, block_device_info=None):
        return

    def live_migration(self, context, instance, dest,
                       post_method, recover_method, block_migration=False,
                       migrate_data=None):
        post_method(context, instance, dest, block_migration,
                            migrate_data)
        return

    def live_migration_force_complete(self, instance):
        return

    def live_migration_abort(self, instance):
        return

    def cleanup_live_migration_destination_check(self, context,
                                                 dest_check_data):
        return

    def check_can_live_migrate_destination(self, context, instance,
                                           src_compute_info, dst_compute_info,
                                           block_migration=False,
                                           disk_over_commit=False):
        data = migrate_data.LibvirtLiveMigrateData()
        data.filename = 'fake'
        data.image_type = CONF.libvirt.images_type
        data.graphics_listen_addr_vnc = CONF.vnc.server_listen
        data.graphics_listen_addr_spice = CONF.spice.server_listen
        data.serial_listen_addr = None
        # Notes(eliqiao): block_migration and disk_over_commit are not
        # nullable, so just don't set them if they are None
        if block_migration is not None:
            data.block_migration = block_migration
        if disk_over_commit is not None:
            data.disk_over_commit = disk_over_commit
        data.disk_available_mb = 100000
        data.is_shared_block_storage = True
        data.is_shared_instance_path = True

        return data

    def check_can_live_migrate_source(self, context, instance,
                                      dest_check_data, block_device_info=None):
        return dest_check_data

    def finish_migration(self, context, migration, instance, disk_info,
                         network_info, image_meta, resize_instance,
                         block_device_info=None, power_on=True):
        injected_files = admin_password = allocations = None
        # Finish migration is just like spawning the guest on a destination
        # host during resize/cold migrate, so re-use the spawn() fake to
        # claim resources and track the instance on this "hypervisor".
        self.spawn(context, instance, image_meta, injected_files,
                   admin_password, allocations,
                   block_device_info=block_device_info, power_on=power_on)

    def confirm_migration(self, context, migration, instance, network_info):
        # Confirm migration cleans up the guest from the source host so just
        # destroy the guest to remove it from the list of tracked instances
        # unless it is a same-host resize.
        if migration.source_compute != migration.dest_compute:
            self.destroy(context, instance, network_info)

    def pre_live_migration(self, context, instance, block_device_info,
                           network_info, disk_info, migrate_data):
        return migrate_data

    def rollback_live_migration_at_destination(self, context, instance,
                                               network_info,
                                               block_device_info,
                                               destroy_disks=True,
                                               migrate_data=None):
        return

    def unfilter_instance(self, instance, network_info):
        return

    def _test_remove_vm(self, instance_uuid):
        """Removes the named VM, as if it crashed. For testing."""
        self.instances.pop(instance_uuid)

    def host_power_action(self, action):
        """Reboots, shuts down or powers up the host."""
        return action

    def host_maintenance_mode(self, host, mode):
        """Start/Stop host maintenance window. On start, it triggers
        guest VMs evacuation.
        """
        if not mode:
            return 'off_maintenance'
        return 'on_maintenance'

    def set_host_enabled(self, enabled):
        """Sets the specified host's ability to accept new instances."""
        if enabled:
            return 'enabled'
        return 'disabled'

    def get_volume_connector(self, instance):
        return {'ip': CONF.my_block_storage_ip,
                'initiator': 'fake',
                'host': 'fakehost'}

    def get_available_nodes(self, refresh=False):
        return self._nodes

    def instance_on_disk(self, instance):
        return False

    def quiesce(self, context, instance, image_meta):
        pass

    def unquiesce(self, context, instance, image_meta):
        pass


class FakeVirtAPI(virtapi.VirtAPI):
    @contextlib.contextmanager
    def wait_for_instance_event(self, instance, event_names, deadline=300,
                                error_callback=None):
        # NOTE(danms): Don't actually wait for any events, just
        # fall through
        yield

    def update_compute_provider_status(self, context, rp_uuid, enabled):
        pass


class SmallFakeDriver(FakeDriver):
    # The api samples expect specific cpu memory and disk sizes. In order to
    # allow the FakeVirt driver to be used outside of the unit tests, provide
    # a separate class that has the values expected by the api samples. So
    # instead of requiring new samples every time those
    # values are adjusted allow them to be overwritten here.

    vcpus = 2
    memory_mb = 8192
    local_gb = 1028


class MediumFakeDriver(FakeDriver):
    # Fake driver that has enough resources to host more than one instance
    # but not that much that cannot be exhausted easily

    vcpus = 10
    memory_mb = 8192
    local_gb = 1028


class PowerUpdateFakeDriver(SmallFakeDriver):
    # A specific fake driver for the power-update external event testing.

    def __init__(self, virtapi):
        super(PowerUpdateFakeDriver, self).__init__(virtapi=None)
        self.driver = ironic.IronicDriver(virtapi=virtapi)

    def power_update_event(self, instance, target_power_state):
        """Update power state of the specified instance in the nova DB."""
        self.driver.power_update_event(instance, target_power_state)


class MediumFakeDriverWithNestedCustomResources(MediumFakeDriver):
    # A MediumFakeDriver variant that also reports CUSTOM_MAGIC resources on
    # a nested resource provider
    vcpus = 10
    memory_mb = 8192
    local_gb = 1028
    child_resources = {
            'CUSTOM_MAGIC': {
                'total': 10,
                'reserved': 0,
                'min_unit': 1,
                'max_unit': 10,
                'step_size': 1,
                'allocation_ratio': 1,
            }
    }

    def update_provider_tree(self, provider_tree, nodename, allocations=None):
        super(
            MediumFakeDriverWithNestedCustomResources,
            self).update_provider_tree(
                provider_tree, nodename,
                allocations=allocations)

        if not provider_tree.exists(nodename + '-child'):
            provider_tree.new_child(name=nodename + '-child',
                                    parent=nodename)

        provider_tree.update_inventory(nodename + '-child',
                                       self.child_resources)


class FakeFinishMigrationFailDriver(FakeDriver):
    """FakeDriver variant that will raise an exception from finish_migration"""

    def finish_migration(self, *args, **kwargs):
        raise exception.VirtualInterfaceCreateException()


class PredictableNodeUUIDDriver(SmallFakeDriver):
    """SmallFakeDriver variant that reports a predictable node uuid in
    get_available_resource, like IronicDriver.
    """
    def get_available_resource(self, nodename):
        resources = super(
            PredictableNodeUUIDDriver, self).get_available_resource(nodename)
        # This is used in ComputeNode.update_from_virt_driver which is called
        # from the ResourceTracker when creating a ComputeNode.
        resources['uuid'] = uuid.uuid5(uuid.NAMESPACE_DNS, nodename)
        return resources


class FakeRescheduleDriver(FakeDriver):
    """FakeDriver derivative that triggers a reschedule on the first spawn
    attempt. This is expected to only be used in tests that have more than
    one compute service.
    """
    # dict, keyed by instance uuid, mapped to a boolean telling us if the
    # instance has been rescheduled or not
    rescheduled = {}

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, allocations, network_info=None,
              block_device_info=None, power_on=True):
        if not self.rescheduled.get(instance.uuid, False):
            # We only reschedule on the first time something hits spawn().
            self.rescheduled[instance.uuid] = True
            raise exception.ComputeResourcesUnavailable(
                reason='FakeRescheduleDriver')
        super(FakeRescheduleDriver, self).spawn(
            context, instance, image_meta, injected_files,
            admin_password, allocations, network_info, block_device_info,
            power_on)


class FakeRescheduleDriverWithNestedCustomResources(
        FakeRescheduleDriver, MediumFakeDriverWithNestedCustomResources):
    pass


class FakeBuildAbortDriver(FakeDriver):
    """FakeDriver derivative that always fails on spawn() with a
    BuildAbortException so no reschedule is attempted.
    """
    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, allocations, network_info=None,
              block_device_info=None, power_on=True):
        raise exception.BuildAbortException(
            instance_uuid=instance.uuid, reason='FakeBuildAbortDriver')


class FakeBuildAbortDriverWithNestedCustomResources(
    FakeBuildAbortDriver, MediumFakeDriverWithNestedCustomResources):
    pass


class FakeUnshelveSpawnFailDriver(FakeDriver):
    """FakeDriver derivative that always fails on spawn() with a
    VirtualInterfaceCreateException when unshelving an offloaded instance.
    """
    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, allocations, network_info=None,
              block_device_info=None, power_on=True):
        if instance.vm_state == vm_states.SHELVED_OFFLOADED:
            raise exception.VirtualInterfaceCreateException(
                'FakeUnshelveSpawnFailDriver')
        # Otherwise spawn normally during the initial build.
        super(FakeUnshelveSpawnFailDriver, self).spawn(
            context, instance, image_meta, injected_files,
            admin_password, allocations, network_info, block_device_info,
            power_on)


class FakeUnshelveSpawnFailDriverWithNestedCustomResources(
    FakeUnshelveSpawnFailDriver, MediumFakeDriverWithNestedCustomResources):
    pass


class FakeLiveMigrateDriver(FakeDriver):
    """FakeDriver derivative to handle force_complete and abort calls.

    This module serves those tests that need to abort or force-complete
    the live migration, thus the live migration will never be finished
    without the force_complete_migration or delete_migration API calls.

    """

    def __init__(self, virtapi, read_only=False):
        super(FakeLiveMigrateDriver, self).__init__(virtapi, read_only)
        self._migrating = True
        self._abort_migration = True

    def live_migration(self, context, instance, dest,
                       post_method, recover_method, block_migration=False,
                       migrate_data=None):
        self._abort_migration = False
        self._migrating = True
        count = 0
        while self._migrating and count < 50:
            time.sleep(0.1)
            count = count + 1

        if self._abort_migration:
            recover_method(context, instance, dest, migrate_data,
                           migration_status='cancelled')
        else:
            post_method(context, instance, dest, block_migration,
                        migrate_data)

    def live_migration_force_complete(self, instance):
        self._migrating = False
        if instance.uuid in self.instances:
            del self.instances[instance.uuid]

    def live_migration_abort(self, instance):
        self._abort_migration = True
        self._migrating = False

    def post_live_migration(self, context, instance, block_device_info,
                            migrate_data=None):
        if instance.uuid in self.instances:
            del self.instances[instance.uuid]


class FakeLiveMigrateDriverWithNestedCustomResources(
        FakeLiveMigrateDriver, MediumFakeDriverWithNestedCustomResources):
    pass


class FakeDriverWithPciResources(SmallFakeDriver):

    PCI_ADDR_PF1 = '0000:01:00.0'
    PCI_ADDR_PF1_VF1 = '0000:01:00.1'
    PCI_ADDR_PF2 = '0000:02:00.0'
    PCI_ADDR_PF2_VF1 = '0000:02:00.1'
    PCI_ADDR_PF3 = '0000:03:00.0'
    PCI_ADDR_PF3_VF1 = '0000:03:00.1'

    # NOTE(gibi): Always use this fixture along with the
    # FakeDriverWithPciResources to make the necessary configuration for the
    # driver.
    class FakeDriverWithPciResourcesConfigFixture(fixtures.Fixture):
        def setUp(self):
            super(FakeDriverWithPciResources.
                  FakeDriverWithPciResourcesConfigFixture, self).setUp()
            # Set passthrough_whitelist before the compute node starts to match
            # with the PCI devices reported by this fake driver.

            # NOTE(gibi): 0000:01:00 is tagged to physnet1 and therefore not a
            # match based on physnet to our sriov port
            # 'port_with_sriov_resource_request' as the network of that port
            # points to physnet2 with the attribute
            # 'provider:physical_network'. Nova pci handling already enforces
            # this rule.
            #
            # 0000:02:00 and 0000:03:00 are both tagged to physnet2 and
            # therefore a good match for our sriov port based on physnet.
            # Having two PFs on the same physnet will allow us to test the
            # placement allocation - physical allocation matching based on the
            # bandwidth allocation in the future.
            CONF.set_override('passthrough_whitelist', override=[
                jsonutils.dumps(
                    {
                        "address": {
                            "domain": "0000",
                            "bus": "01",
                            "slot": "00",
                            "function": ".*"},
                        "physical_network": "physnet1",
                    }
                ),
                jsonutils.dumps(
                    {
                        "address": {
                            "domain": "0000",
                            "bus": "02",
                            "slot": "00",
                            "function": ".*"},
                        "physical_network": "physnet2",
                    }
                ),
                jsonutils.dumps(
                    {
                        "address": {
                            "domain": "0000",
                            "bus": "03",
                            "slot": "00",
                            "function": ".*"},
                        "physical_network": "physnet2",
                    }
                ),
            ],
                             group='pci')

    def get_available_resource(self, nodename):
        host_status = super(
            FakeDriverWithPciResources, self).get_available_resource(nodename)
        # 01:00.0 - PF - ens1
        #  |---- 01:00.1 - VF
        #
        # 02:00.0 - PF - ens2
        #  |---- 02:00.1 - VF
        #
        # 03:00.0 - PF - ens3
        #  |---- 03:00.1 - VF
        host_status['pci_passthrough_devices'] = jsonutils.dumps([
            {
                'address': self.PCI_ADDR_PF1,
                'product_id': 'fake-product_id',
                'vendor_id': 'fake-vendor_id',
                'status': 'available',
                'dev_type': 'type-PF',
                'parent_addr': None,
                'numa_node': 0,
                'label': 'fake-label',
            },
            {
                'address': self.PCI_ADDR_PF1_VF1,
                'product_id': 'fake-product_id',
                'vendor_id': 'fake-vendor_id',
                'status': 'available',
                'dev_type': 'type-VF',
                'parent_addr': self.PCI_ADDR_PF1,
                'numa_node': 0,
                'label': 'fake-label',
                "parent_ifname": self._host + "-ens1",
            },
            {
                'address': self.PCI_ADDR_PF2,
                'product_id': 'fake-product_id',
                'vendor_id': 'fake-vendor_id',
                'status': 'available',
                'dev_type': 'type-PF',
                'parent_addr': None,
                'numa_node': 0,
                'label': 'fake-label',
            },
            {
                'address': self.PCI_ADDR_PF2_VF1,
                'product_id': 'fake-product_id',
                'vendor_id': 'fake-vendor_id',
                'status': 'available',
                'dev_type': 'type-VF',
                'parent_addr': self.PCI_ADDR_PF2,
                'numa_node': 0,
                'label': 'fake-label',
                "parent_ifname": self._host + "-ens2",
            },
            {
                'address': self.PCI_ADDR_PF3,
                'product_id': 'fake-product_id',
                'vendor_id': 'fake-vendor_id',
                'status': 'available',
                'dev_type': 'type-PF',
                'parent_addr': None,
                'numa_node': 0,
                'label': 'fake-label',
            },
            {
                'address': self.PCI_ADDR_PF3_VF1,
                'product_id': 'fake-product_id',
                'vendor_id': 'fake-vendor_id',
                'status': 'available',
                'dev_type': 'type-VF',
                'parent_addr': self.PCI_ADDR_PF3,
                'numa_node': 0,
                'label': 'fake-label',
                "parent_ifname": self._host + "-ens3",
            },
        ])
        return host_status
