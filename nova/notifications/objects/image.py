#    Copyright 2018 NTT Corporation
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

from nova.notifications.objects import base
from nova.objects import base as nova_base
from nova.objects import fields


@nova_base.NovaObjectRegistry.register_notification
class ImageMetaPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    SCHEMA = {
        'id': ('image_meta', 'id'),
        'name': ('image_meta', 'name'),
        'status': ('image_meta', 'status'),
        'visibility': ('image_meta', 'visibility'),
        'protected': ('image_meta', 'protected'),
        'checksum': ('image_meta', 'checksum'),
        'owner': ('image_meta', 'owner'),
        'size': ('image_meta', 'size'),
        'virtual_size': ('image_meta', 'virtual_size'),
        'container_format': ('image_meta', 'container_format'),
        'disk_format': ('image_meta', 'disk_format'),
        'created_at': ('image_meta', 'created_at'),
        'updated_at': ('image_meta', 'updated_at'),
        'tags': ('image_meta', 'tags'),
        'direct_url': ('image_meta', 'direct_url'),
        'min_ram': ('image_meta', 'min_ram'),
        'min_disk': ('image_meta', 'min_disk')
    }

    # NOTE(takashin): The reason that each field is nullable is as follows.
    #
    # a. It is defined as "The value might be null (JSON null data type)."
    #    in the "Show image" API (GET /v2/images/{image_id})
    #    in the glance API v2 Reference.
    #    (https://docs.openstack.org/api-ref/image/v2/index.html)
    #
    #   * checksum
    #   * container_format
    #   * disk_format
    #   * min_disk
    #   * min_ram
    #   * name
    #   * owner
    #   * size
    #   * updated_at
    #   * virtual_size
    #
    # b. It is optional in the response from glance.
    #   * direct_url
    #
    # a. It is defined as nullable in the ImageMeta object.
    #   * created_at
    #
    # c. It cannot be got in the boot from volume case.
    #    See VIM_IMAGE_ATTRIBUTES in nova/utils.py.
    #
    #   * id (not 'image_id')
    #   * visibility
    #   * protected
    #   * status
    #   * tags
    fields = {
        'id': fields.UUIDField(nullable=True),
        'name': fields.StringField(nullable=True),
        'status': fields.StringField(nullable=True),
        'visibility': fields.StringField(nullable=True),
        'protected': fields.FlexibleBooleanField(nullable=True),
        'checksum': fields.StringField(nullable=True),
        'owner': fields.StringField(nullable=True),
        'size': fields.IntegerField(nullable=True),
        'virtual_size': fields.IntegerField(nullable=True),
        'container_format': fields.StringField(nullable=True),
        'disk_format': fields.StringField(nullable=True),
        'created_at': fields.DateTimeField(nullable=True),
        'updated_at': fields.DateTimeField(nullable=True),
        'tags': fields.ListOfStringsField(nullable=True),
        'direct_url': fields.StringField(nullable=True),
        'min_ram': fields.IntegerField(nullable=True),
        'min_disk': fields.IntegerField(nullable=True),
        'properties': fields.ObjectField('ImageMetaPropsPayload')
    }

    def __init__(self, image_meta):
        super(ImageMetaPayload, self).__init__()
        self.properties = ImageMetaPropsPayload(
            image_meta_props=image_meta.properties)
        self.populate_schema(image_meta=image_meta)


@nova_base.NovaObjectRegistry.register_notification
class ImageMetaPropsPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    # Version 1.1: Added 'gop', 'virtio' and  'none' to hw_video_model field
    VERSION = '1.1'

    SCHEMA = {
        'hw_architecture': ('image_meta_props', 'hw_architecture'),
        'hw_auto_disk_config': ('image_meta_props', 'hw_auto_disk_config'),
        'hw_boot_menu': ('image_meta_props', 'hw_boot_menu'),
        'hw_cdrom_bus': ('image_meta_props', 'hw_cdrom_bus'),
        'hw_cpu_cores': ('image_meta_props', 'hw_cpu_cores'),
        'hw_cpu_sockets': ('image_meta_props', 'hw_cpu_sockets'),
        'hw_cpu_max_cores': ('image_meta_props', 'hw_cpu_max_cores'),
        'hw_cpu_max_sockets': ('image_meta_props', 'hw_cpu_max_sockets'),
        'hw_cpu_max_threads': ('image_meta_props', 'hw_cpu_max_threads'),
        'hw_cpu_policy': ('image_meta_props', 'hw_cpu_policy'),
        'hw_cpu_thread_policy': ('image_meta_props', 'hw_cpu_thread_policy'),
        'hw_cpu_realtime_mask': ('image_meta_props', 'hw_cpu_realtime_mask'),
        'hw_cpu_threads': ('image_meta_props', 'hw_cpu_threads'),
        'hw_device_id': ('image_meta_props', 'hw_device_id'),
        'hw_disk_bus': ('image_meta_props', 'hw_disk_bus'),
        'hw_disk_type': ('image_meta_props', 'hw_disk_type'),
        'hw_floppy_bus': ('image_meta_props', 'hw_floppy_bus'),
        'hw_firmware_type': ('image_meta_props', 'hw_firmware_type'),
        'hw_ipxe_boot': ('image_meta_props', 'hw_ipxe_boot'),
        'hw_machine_type': ('image_meta_props', 'hw_machine_type'),
        'hw_mem_page_size': ('image_meta_props', 'hw_mem_page_size'),
        'hw_numa_nodes': ('image_meta_props', 'hw_numa_nodes'),
        'hw_numa_cpus': ('image_meta_props', 'hw_numa_cpus'),
        'hw_numa_mem': ('image_meta_props', 'hw_numa_mem'),
        'hw_pointer_model': ('image_meta_props', 'hw_pointer_model'),
        'hw_qemu_guest_agent': ('image_meta_props', 'hw_qemu_guest_agent'),
        'hw_rescue_bus': ('image_meta_props', 'hw_rescue_bus'),
        'hw_rescue_device': ('image_meta_props', 'hw_rescue_device'),
        'hw_rng_model': ('image_meta_props', 'hw_rng_model'),
        'hw_serial_port_count': ('image_meta_props', 'hw_serial_port_count'),
        'hw_scsi_model': ('image_meta_props', 'hw_scsi_model'),
        'hw_video_model': ('image_meta_props', 'hw_video_model'),
        'hw_video_ram': ('image_meta_props', 'hw_video_ram'),
        'hw_vif_model': ('image_meta_props', 'hw_vif_model'),
        'hw_vm_mode': ('image_meta_props', 'hw_vm_mode'),
        'hw_watchdog_action': ('image_meta_props', 'hw_watchdog_action'),
        'hw_vif_multiqueue_enabled': ('image_meta_props',
                                      'hw_vif_multiqueue_enabled'),
        'img_bittorrent': ('image_meta_props', 'img_bittorrent'),
        'img_bdm_v2': ('image_meta_props', 'img_bdm_v2'),
        'img_block_device_mapping': ('image_meta_props',
                                     'img_block_device_mapping'),
        'img_cache_in_nova': ('image_meta_props', 'img_cache_in_nova'),
        'img_compression_level': ('image_meta_props', 'img_compression_level'),
        'img_hv_requested_version': ('image_meta_props',
                                     'img_hv_requested_version'),
        'img_hv_type': ('image_meta_props', 'img_hv_type'),
        'img_config_drive': ('image_meta_props', 'img_config_drive'),
        'img_linked_clone': ('image_meta_props', 'img_linked_clone'),
        'img_mappings': ('image_meta_props', 'img_mappings'),
        'img_owner_id': ('image_meta_props', 'img_owner_id'),
        'img_root_device_name': ('image_meta_props', 'img_root_device_name'),
        'img_use_agent': ('image_meta_props', 'img_use_agent'),
        'img_version': ('image_meta_props', 'img_version'),
        'img_signature': ('image_meta_props', 'img_signature'),
        'img_signature_hash_method': ('image_meta_props',
                                      'img_signature_hash_method'),
        'img_signature_certificate_uuid': ('image_meta_props',
                                           'img_signature_certificate_uuid'),
        'img_signature_key_type': ('image_meta_props',
                                   'img_signature_key_type'),
        'img_hide_hypervisor_id': ('image_meta_props',
                                   'img_hide_hypervisor_id'),
        'os_admin_user': ('image_meta_props', 'os_admin_user'),
        'os_command_line': ('image_meta_props', 'os_command_line'),
        'os_distro': ('image_meta_props', 'os_distro'),
        'os_require_quiesce': ('image_meta_props', 'os_require_quiesce'),
        'os_secure_boot': ('image_meta_props', 'os_secure_boot'),
        'os_skip_agent_inject_files_at_boot': (
            'image_meta_props', 'os_skip_agent_inject_files_at_boot'),
        'os_skip_agent_inject_ssh': ('image_meta_props',
                                     'os_skip_agent_inject_ssh'),
        'os_type': ('image_meta_props', 'os_type'),
        'traits_required': ('image_meta_props', 'traits_required')
    }

    fields = {
        'hw_architecture': fields.ArchitectureField(),
        'hw_auto_disk_config': fields.StringField(),
        'hw_boot_menu': fields.FlexibleBooleanField(),
        'hw_cdrom_bus': fields.DiskBusField(),
        'hw_cpu_cores': fields.IntegerField(),
        'hw_cpu_sockets': fields.IntegerField(),
        'hw_cpu_max_cores': fields.IntegerField(),
        'hw_cpu_max_sockets': fields.IntegerField(),
        'hw_cpu_max_threads': fields.IntegerField(),
        'hw_cpu_policy': fields.CPUAllocationPolicyField(),
        'hw_cpu_thread_policy': fields.CPUThreadAllocationPolicyField(),
        'hw_cpu_realtime_mask': fields.StringField(),
        'hw_cpu_threads': fields.IntegerField(),
        'hw_device_id': fields.IntegerField(),
        'hw_disk_bus': fields.DiskBusField(),
        'hw_disk_type': fields.StringField(),
        'hw_floppy_bus': fields.DiskBusField(),
        'hw_firmware_type': fields.FirmwareTypeField(),
        'hw_ipxe_boot': fields.FlexibleBooleanField(),
        'hw_machine_type': fields.StringField(),
        'hw_mem_page_size': fields.StringField(),
        'hw_numa_nodes': fields.IntegerField(),
        'hw_numa_cpus': fields.ListOfSetsOfIntegersField(),
        'hw_numa_mem': fields.ListOfIntegersField(),
        'hw_pointer_model': fields.PointerModelField(),
        'hw_qemu_guest_agent': fields.FlexibleBooleanField(),
        'hw_rescue_bus': fields.DiskBusField(),
        'hw_rescue_device': fields.BlockDeviceTypeField(),
        'hw_rng_model': fields.RNGModelField(),
        'hw_serial_port_count': fields.IntegerField(),
        'hw_scsi_model': fields.SCSIModelField(),
        'hw_video_model': fields.VideoModelField(),
        'hw_video_ram': fields.IntegerField(),
        'hw_vif_model': fields.VIFModelField(),
        'hw_vm_mode': fields.VMModeField(),
        'hw_watchdog_action': fields.WatchdogActionField(),
        'hw_vif_multiqueue_enabled': fields.FlexibleBooleanField(),
        'img_bittorrent': fields.FlexibleBooleanField(),
        'img_bdm_v2': fields.FlexibleBooleanField(),
        'img_block_device_mapping':
            fields.ListOfDictOfNullableStringsField(),
        'img_cache_in_nova': fields.FlexibleBooleanField(),
        'img_compression_level': fields.IntegerField(),
        'img_hv_requested_version': fields.VersionPredicateField(),
        'img_hv_type': fields.HVTypeField(),
        'img_config_drive': fields.ConfigDrivePolicyField(),
        'img_linked_clone': fields.FlexibleBooleanField(),
        'img_mappings': fields.ListOfDictOfNullableStringsField(),
        'img_owner_id': fields.StringField(),
        'img_root_device_name': fields.StringField(),
        'img_use_agent': fields.FlexibleBooleanField(),
        'img_version': fields.IntegerField(),
        'img_signature': fields.StringField(),
        'img_signature_hash_method': fields.ImageSignatureHashTypeField(),
        'img_signature_certificate_uuid': fields.UUIDField(),
        'img_signature_key_type': fields.ImageSignatureKeyTypeField(),
        'img_hide_hypervisor_id': fields.FlexibleBooleanField(),
        'os_admin_user': fields.StringField(),
        'os_command_line': fields.StringField(),
        'os_distro': fields.StringField(),
        'os_require_quiesce': fields.FlexibleBooleanField(),
        'os_secure_boot': fields.SecureBootField(),
        'os_skip_agent_inject_files_at_boot': fields.FlexibleBooleanField(),
        'os_skip_agent_inject_ssh': fields.FlexibleBooleanField(),
        'os_type': fields.OSTypeField(),
        'traits_required': fields.ListOfStringsField()
    }

    def __init__(self, image_meta_props):
        super(ImageMetaPropsPayload, self).__init__()
        # NOTE(takashin): If fields are not set in the ImageMetaProps object,
        # it will not set the fields in the ImageMetaPropsPayload
        # in order to avoid too many fields whose values are None.
        self.populate_schema(set_none=False, image_meta_props=image_meta_props)
