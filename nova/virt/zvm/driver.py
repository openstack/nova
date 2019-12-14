# Copyright 2017,2018 IBM Corp.
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

import eventlet
import os
import six
import time

import os_resource_classes as orc
from oslo_concurrency import lockutils
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import excutils

from nova.compute import task_states
from nova import conf
from nova import exception
from nova.i18n import _
from nova.image import glance
from nova.objects import fields as obj_fields
from nova.virt import driver
from nova.virt import images
from nova.virt.zvm import guest
from nova.virt.zvm import hypervisor
from nova.virt.zvm import utils as zvmutils


LOG = logging.getLogger(__name__)
CONF = conf.CONF


DEFAULT_EPH_DISK_FMT = 'ext3'


class ZVMDriver(driver.ComputeDriver):
    """z/VM implementation of ComputeDriver."""
    capabilities = {
        "supports_pcpus": False,

        # Image type support flags
        "supports_image_type_aki": False,
        "supports_image_type_ami": False,
        "supports_image_type_ari": False,
        "supports_image_type_iso": False,
        "supports_image_type_qcow2": False,
        "supports_image_type_raw": True,
        "supports_image_type_vdi": False,
        "supports_image_type_vhd": False,
        "supports_image_type_vhdx": False,
        "supports_image_type_vmdk": False,
        "supports_image_type_ploop": False,
    }

    def __init__(self, virtapi):
        super(ZVMDriver, self).__init__(virtapi)

        self._validate_options()

        self._hypervisor = hypervisor.Hypervisor(
            CONF.zvm.cloud_connector_url, ca_file=CONF.zvm.ca_file)

        LOG.info("The zVM compute driver has been initialized.")

    @staticmethod
    def _validate_options():
        if not CONF.zvm.cloud_connector_url:
            error = _('Must specify cloud_connector_url in zvm config '
                      'group to use compute_driver=zvm.driver.ZVMDriver')
            raise exception.ZVMDriverException(error=error)

        # Try a test to ensure length of give guest is smaller than 8
        try:
            _test_instance = CONF.instance_name_template % 0
        except Exception:
            msg = _("Template is not usable, the template defined is "
                    "instance_name_template=%s") % CONF.instance_name_template
            raise exception.ZVMDriverException(error=msg)

        # For zVM instance, limit the maximum length of instance name to 8
        if len(_test_instance) > 8:
            msg = _("Can't spawn instance with template '%s', "
                    "The zVM hypervisor does not support instance names "
                    "longer than 8 characters. Please change your config of "
                    "instance_name_template.") % CONF.instance_name_template
            raise exception.ZVMDriverException(error=msg)

    def init_host(self, host):
        pass

    def list_instances(self):
        return self._hypervisor.list_names()

    def instance_exists(self, instance):
        # z/VM driver returns name in upper case and because userid is
        # stored instead of uuid, list_instance_uuids is not implemented
        return self._hypervisor.guest_exists(instance)

    def get_available_resource(self, nodename=None):
        host_stats = self._hypervisor.get_available_resource()

        hypervisor_hostname = self._hypervisor.get_available_nodes()[0]
        res = {
            'vcpus': host_stats.get('vcpus', 0),
            'memory_mb': host_stats.get('memory_mb', 0),
            'local_gb': host_stats.get('disk_total', 0),
            'vcpus_used': host_stats.get('vcpus_used', 0),
            'memory_mb_used': host_stats.get('memory_mb_used', 0),
            'local_gb_used': host_stats.get('disk_used', 0),
            'hypervisor_type': host_stats.get('hypervisor_type',
                                              obj_fields.HVType.ZVM),
            'hypervisor_version': host_stats.get('hypervisor_version', 0),
            'hypervisor_hostname': host_stats.get('hypervisor_hostname',
                                                  hypervisor_hostname),
            'cpu_info': jsonutils.dumps(host_stats.get('cpu_info', {})),
            'disk_available_least': host_stats.get('disk_available', 0),
            'supported_instances': [(obj_fields.Architecture.S390X,
                                     obj_fields.HVType.ZVM,
                                     obj_fields.VMMode.HVM)],
            'numa_topology': None,
        }

        LOG.debug("Getting available resource for %(host)s:%(nodename)s",
                  {'host': CONF.host, 'nodename': nodename})

        return res

    def get_available_nodes(self, refresh=False):
        return self._hypervisor.get_available_nodes(refresh=refresh)

    def get_info(self, instance, use_cache=True):
        _guest = guest.Guest(self._hypervisor, instance)
        return _guest.get_info()

    def spawn(self, context, instance, image_meta, injected_files,
              admin_password, allocations, network_info=None,
              block_device_info=None, power_on=True, accel_info=None):

        LOG.info("Spawning new instance %s on zVM hypervisor",
                 instance.name, instance=instance)

        if self._hypervisor.guest_exists(instance):
            raise exception.InstanceExists(name=instance.name)

        os_distro = image_meta.properties.get('os_distro')
        if os_distro is None or len(os_distro) == 0:
            reason = _("The `os_distro` image metadata property is required")
            raise exception.InvalidInput(reason=reason)

        try:
            spawn_start = time.time()

            transportfiles = zvmutils.generate_configdrive(context,
                instance, injected_files, network_info,
                admin_password)

            spawn_image_name = self._get_image_info(context, image_meta.id,
                                                    os_distro)
            disk_list, eph_list = self._set_disk_list(instance,
                                                      spawn_image_name,
                                                      block_device_info)

            # Create the guest vm
            self._hypervisor.guest_create(instance.name,
                instance.vcpus, instance.memory_mb,
                disk_list)

            # Deploy image to the guest vm
            self._hypervisor.guest_deploy(instance.name,
                spawn_image_name, transportfiles=transportfiles)

            # Handle ephemeral disks
            if eph_list:
                self._hypervisor.guest_config_minidisks(instance.name,
                                                        eph_list)
            # Setup network for z/VM instance
            self._wait_vif_plug_events(instance.name, os_distro,
                network_info, instance)

            self._hypervisor.guest_start(instance.name)
            spawn_time = time.time() - spawn_start
            LOG.info("Instance spawned successfully in %s seconds",
                     spawn_time, instance=instance)
        except Exception as err:
            with excutils.save_and_reraise_exception():
                LOG.error("Deploy instance %(instance)s "
                          "failed with reason: %(err)s",
                          {'instance': instance.name, 'err': err},
                          instance=instance)
                try:
                    self.destroy(context, instance, network_info,
                                 block_device_info)
                except Exception:
                    LOG.exception("Failed to destroy instance",
                                  instance=instance)

    @lockutils.synchronized('IMAGE_INFO_SEMAPHORE')
    def _get_image_info(self, context, image_meta_id, os_distro):
        try:
            res = self._hypervisor.image_query(imagename=image_meta_id)
        except exception.ZVMConnectorError as err:
            with excutils.save_and_reraise_exception() as sare:
                if err.overallRC == 404:
                    sare.reraise = False
                    self._import_spawn_image(context, image_meta_id, os_distro)

                    res = self._hypervisor.image_query(imagename=image_meta_id)

        return res[0]['imagename']

    def _set_disk_list(self, instance, image_name, block_device_info):
        if instance.root_gb == 0:
            root_disk_size = self._hypervisor.image_get_root_disk_size(
                image_name)
        else:
            root_disk_size = '%ig' % instance.root_gb

        disk_list = []
        root_disk = {'size': root_disk_size,
                     'is_boot_disk': True
                    }
        disk_list.append(root_disk)
        ephemeral_disks_info = driver.block_device_info_get_ephemerals(
            block_device_info)

        eph_list = []
        for eph in ephemeral_disks_info:
            eph_dict = {'size': '%ig' % eph['size'],
                        'format': (CONF.default_ephemeral_format or
                                   DEFAULT_EPH_DISK_FMT)}
            eph_list.append(eph_dict)

        if eph_list:
            disk_list.extend(eph_list)
        return disk_list, eph_list

    def _setup_network(self, vm_name, os_distro, network_info, instance):
        LOG.debug("Creating NICs for vm %s", vm_name)
        inst_nets = []
        for vif in network_info:
            subnet = vif['network']['subnets'][0]
            _net = {'ip_addr': subnet['ips'][0]['address'],
                    'gateway_addr': subnet['gateway']['address'],
                    'cidr': subnet['cidr'],
                    'mac_addr': vif['address'],
                    'nic_id': vif['id']}
            inst_nets.append(_net)

        if inst_nets:
            self._hypervisor.guest_create_network_interface(vm_name,
                os_distro, inst_nets)

    @staticmethod
    def _get_neutron_event(network_info):
        if CONF.vif_plugging_timeout:
            return [('network-vif-plugged', vif['id'])
                    for vif in network_info if vif.get('active') is False]

        return []

    @staticmethod
    def _neutron_failed_callback(self, event_name, instance):
        LOG.error("Neutron Reported failure on event %s for instance",
                  event_name, instance=instance)
        if CONF.vif_plugging_is_fatal:
            raise exception.VirtualInterfaceCreateException()

    def _wait_vif_plug_events(self, vm_name, os_distro, network_info,
                              instance):
        timeout = CONF.vif_plugging_timeout
        try:
            event = self._get_neutron_event(network_info)
            with self.virtapi.wait_for_instance_event(
                    instance, event, deadline=timeout,
                    error_callback=self._neutron_failed_callback):
                self._setup_network(vm_name, os_distro, network_info, instance)
        except eventlet.timeout.Timeout:
            LOG.warning("Timeout waiting for vif plugging callback.",
                        instance=instance)
            if CONF.vif_plugging_is_fatal:
                raise exception.VirtualInterfaceCreateException()
        except Exception as err:
            with excutils.save_and_reraise_exception():
                LOG.error("Failed for vif plugging: %s", six.text_type(err),
                          instance=instance)

    def _import_spawn_image(self, context, image_meta_id, image_os_version):
        LOG.debug("Downloading the image %s from glance to nova compute "
                  "server", image_meta_id)
        image_path = os.path.join(os.path.normpath(CONF.zvm.image_tmp_path),
                                  image_meta_id)
        if not os.path.exists(image_path):
            images.fetch(context, image_meta_id, image_path)
        image_url = "file://" + image_path
        image_meta = {'os_version': image_os_version}
        self._hypervisor.image_import(image_meta_id, image_url, image_meta)

    def destroy(self, context, instance, network_info=None,
                block_device_info=None, destroy_disks=False):
        if self._hypervisor.guest_exists(instance):
            LOG.info("Destroying instance", instance=instance)
            try:
                self._hypervisor.guest_delete(instance.name)
            except exception.ZVMConnectorError as err:
                if err.overallRC == 404:
                    LOG.info("instance disappear during destroying",
                             instance=instance)
                else:
                    raise
        else:
            LOG.warning("Instance does not exist", instance=instance)

    def get_host_uptime(self):
        return self._hypervisor.get_host_uptime()

    def snapshot(self, context, instance, image_id, update_task_state):

        (image_service, image_id) = glance.get_remote_image_service(
                                                    context, image_id)

        update_task_state(task_state=task_states.IMAGE_PENDING_UPLOAD)

        try:
            self._hypervisor.guest_capture(instance.name, image_id)
        except Exception as err:
            with excutils.save_and_reraise_exception():
                LOG.error("Failed to capture the instance "
                          "to generate an image with reason: %(err)s",
                          {'err': err}, instance=instance)
                # Clean up the image from glance
                image_service.delete(context, image_id)

        # Export the image to nova-compute server temporary
        image_path = os.path.join(os.path.normpath(
                            CONF.zvm.image_tmp_path), image_id)
        dest_path = "file://" + image_path
        try:
            resp = self._hypervisor.image_export(image_id, dest_path)
        except Exception:
            with excutils.save_and_reraise_exception():
                LOG.error("Failed to export image %s from SDK server to "
                          "nova compute server", image_id)
                image_service.delete(context, image_id)
                self._hypervisor.image_delete(image_id)

        # Save image to glance
        new_image_meta = {
            'status': 'active',
            'properties': {
                 'image_location': 'snapshot',
                 'image_state': 'available',
                 'owner_id': instance['project_id'],
                 'os_distro': resp['os_version'],
                 'architecture': obj_fields.Architecture.S390X,
                 'hypervisor_type': obj_fields.HVType.ZVM,
            },
            'disk_format': 'raw',
            'container_format': 'bare',
        }
        update_task_state(task_state=task_states.IMAGE_UPLOADING,
                          expected_state=task_states.IMAGE_PENDING_UPLOAD)

        # Save the image to glance
        try:
            with open(image_path, 'r') as image_file:
                image_service.update(context,
                                     image_id,
                                     new_image_meta,
                                     image_file,
                                     purge_props=False)
        except Exception:
            with excutils.save_and_reraise_exception():
                image_service.delete(context, image_id)
        finally:
            zvmutils.clean_up_file(image_path)
            self._hypervisor.image_delete(image_id)

        LOG.debug("Snapshot image upload complete", instance=instance)

    def power_off(self, instance, timeout=0, retry_interval=0):
        if timeout >= 0 and retry_interval > 0:
            self._hypervisor.guest_softstop(instance.name, timeout=timeout,
                                            retry_interval=retry_interval)
        else:
            self._hypervisor.guest_softstop(instance.name)

    def power_on(self, context, instance, network_info,
                 block_device_info=None, accel_info=None):
        self._hypervisor.guest_start(instance.name)

    def pause(self, instance):
        self._hypervisor.guest_pause(instance.name)

    def unpause(self, instance):
        self._hypervisor.guest_unpause(instance.name)

    def reboot(self, context, instance, network_info, reboot_type,
               block_device_info=None, bad_volumes_callback=None,
               accel_info=None):

        if reboot_type == 'SOFT':
            self._hypervisor.guest_reboot(instance.name)
        else:
            self._hypervisor.guest_reset(instance.name)

    def get_console_output(self, context, instance):
        return self._hypervisor.guest_get_console_output(instance.name)

    def update_provider_tree(self, provider_tree, nodename, allocations=None):
        resources = self._hypervisor.get_available_resource()

        inventory = provider_tree.data(nodename).inventory
        allocation_ratios = self._get_allocation_ratios(inventory)

        inventory = {
            orc.VCPU: {
                'total': resources['vcpus'],
                'min_unit': 1,
                'max_unit': resources['vcpus'],
                'step_size': 1,
                'allocation_ratio': allocation_ratios[orc.VCPU],
                'reserved': CONF.reserved_host_cpus,
            },
            orc.MEMORY_MB: {
                'total': resources['memory_mb'],
                'min_unit': 1,
                'max_unit': resources['memory_mb'],
                'step_size': 1,
                'allocation_ratio': allocation_ratios[orc.MEMORY_MB],
                'reserved': CONF.reserved_host_memory_mb,
            },
            orc.DISK_GB: {
                'total': resources['disk_total'],
                'min_unit': 1,
                'max_unit': resources['disk_total'],
                'step_size': 1,
                'allocation_ratio': allocation_ratios[orc.DISK_GB],
                'reserved': self._get_reserved_host_disk_gb_from_config(),
            },
        }

        provider_tree.update_inventory(nodename, inventory)
