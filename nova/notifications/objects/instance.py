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

import nova.conf
from nova.notifications.objects import base
from nova.notifications.objects import flavor as flavor_payload
from nova.notifications.objects import keypair as keypair_payload
from nova.objects import base as nova_base
from nova.objects import fields


CONF = nova.conf.CONF


@nova_base.NovaObjectRegistry.register_notification
class InstancePayload(base.NotificationPayloadBase):
    SCHEMA = {
        'uuid': ('instance', 'uuid'),
        'user_id': ('instance', 'user_id'),
        'tenant_id': ('instance', 'project_id'),
        'reservation_id': ('instance', 'reservation_id'),
        'display_name': ('instance', 'display_name'),
        'display_description': ('instance', 'display_description'),
        'host_name': ('instance', 'hostname'),
        'host': ('instance', 'host'),
        'node': ('instance', 'node'),
        'os_type': ('instance', 'os_type'),
        'architecture': ('instance', 'architecture'),
        'availability_zone': ('instance', 'availability_zone'),

        'image_uuid': ('instance', 'image_ref'),

        'key_name': ('instance', 'key_name'),

        'kernel_id': ('instance', 'kernel_id'),
        'ramdisk_id': ('instance', 'ramdisk_id'),

        'created_at': ('instance', 'created_at'),
        'launched_at': ('instance', 'launched_at'),
        'terminated_at': ('instance', 'terminated_at'),
        'deleted_at': ('instance', 'deleted_at'),
        'updated_at': ('instance', 'updated_at'),

        'state': ('instance', 'vm_state'),
        'power_state': ('instance', 'power_state'),
        'task_state': ('instance', 'task_state'),
        'progress': ('instance', 'progress'),

        'metadata': ('instance', 'metadata'),
        'locked': ('instance', 'locked'),
        'auto_disk_config': ('instance', 'auto_disk_config')
    }
    # Version 1.0: Initial version
    # Version 1.1: add locked and display_description field
    # Version 1.2: Add auto_disk_config field
    # Version 1.3: Add key_name field
    # Version 1.4: Add BDM related data
    # Version 1.5: Add updated_at field
    VERSION = '1.5'
    fields = {
        'uuid': fields.UUIDField(),
        'user_id': fields.StringField(nullable=True),
        'tenant_id': fields.StringField(nullable=True),
        'reservation_id': fields.StringField(nullable=True),
        'display_name': fields.StringField(nullable=True),
        'display_description': fields.StringField(nullable=True),
        'host_name': fields.StringField(nullable=True),
        'host': fields.StringField(nullable=True),
        'node': fields.StringField(nullable=True),
        'os_type': fields.StringField(nullable=True),
        'architecture': fields.StringField(nullable=True),
        'availability_zone': fields.StringField(nullable=True),

        'flavor': fields.ObjectField('FlavorPayload'),
        'image_uuid': fields.StringField(nullable=True),

        'key_name': fields.StringField(nullable=True),

        'kernel_id': fields.StringField(nullable=True),
        'ramdisk_id': fields.StringField(nullable=True),

        'created_at': fields.DateTimeField(nullable=True),
        'launched_at': fields.DateTimeField(nullable=True),
        'terminated_at': fields.DateTimeField(nullable=True),
        'deleted_at': fields.DateTimeField(nullable=True),
        'updated_at': fields.DateTimeField(nullable=True),

        'state': fields.InstanceStateField(nullable=True),
        'power_state': fields.InstancePowerStateField(nullable=True),
        'task_state': fields.InstanceTaskStateField(nullable=True),
        'progress': fields.IntegerField(nullable=True),

        'ip_addresses': fields.ListOfObjectsField('IpPayload'),
        'block_devices': fields.ListOfObjectsField('BlockDevicePayload',
                                                   nullable=True),

        'metadata': fields.DictOfStringsField(),
        'locked': fields.BooleanField(),
        'auto_disk_config': fields.DiskConfigField()
    }

    def __init__(self, instance, bdms=None):
        super(InstancePayload, self).__init__()
        network_info = instance.get_network_info()
        self.ip_addresses = IpPayload.from_network_info(network_info)
        self.flavor = flavor_payload.FlavorPayload(flavor=instance.flavor)
        if bdms is not None:
            self.block_devices = BlockDevicePayload.from_bdms(bdms)
        else:
            self.block_devices = BlockDevicePayload.from_instance(instance)

        self.populate_schema(instance=instance)


@nova_base.NovaObjectRegistry.register_notification
class InstanceActionPayload(InstancePayload):
    # No SCHEMA as all the additional fields are calculated

    # Version 1.1: locked and display_description added to InstancePayload
    # Version 1.2: Added auto_disk_config field to InstancePayload
    # Version 1.3: Added key_name field to InstancePayload
    # Version 1.4: Add BDM related data
    # Version 1.5: Added updated_at field to InstancePayload
    VERSION = '1.5'
    fields = {
        'fault': fields.ObjectField('ExceptionPayload', nullable=True),
    }

    def __init__(self, instance, fault, bdms=None):
        super(InstanceActionPayload, self).__init__(instance=instance,
                                                    bdms=bdms)
        self.fault = fault


@nova_base.NovaObjectRegistry.register_notification
class InstanceActionVolumePayload(InstanceActionPayload):
    # Version 1.0: Initial version
    # Version 1.1: Added key_name field to InstancePayload
    # Version 1.2: Add BDM related data
    # Version 1.3: Added updated_at field to InstancePayload

    VERSION = '1.3'
    fields = {
        'volume_id': fields.UUIDField()
    }

    def __init__(self, instance, fault, volume_id):
        super(InstanceActionVolumePayload, self).__init__(
                instance=instance,
                fault=fault)
        self.volume_id = volume_id


@nova_base.NovaObjectRegistry.register_notification
class InstanceActionVolumeSwapPayload(InstanceActionPayload):
    # No SCHEMA as all the additional fields are calculated

    # Version 1.1: locked and display_description added to InstancePayload
    # Version 1.2: Added auto_disk_config field to InstancePayload
    # Version 1.3: Added key_name field to InstancePayload
    # Version 1.4: Add BDM related data
    # Version 1.5: Added updated_at field to InstancePayload
    VERSION = '1.5'
    fields = {
        'old_volume_id': fields.UUIDField(),
        'new_volume_id': fields.UUIDField(),
    }

    def __init__(self, instance, fault, old_volume_id, new_volume_id):
        super(InstanceActionVolumeSwapPayload, self).__init__(
                instance=instance,
                fault=fault)
        self.old_volume_id = old_volume_id
        self.new_volume_id = new_volume_id


@nova_base.NovaObjectRegistry.register_notification
class InstanceCreatePayload(InstanceActionPayload):
    # No SCHEMA as all the additional fields are calculated

    # Version 1.2: Initial version. It starts at 1.2 to match with the version
    #              of the InstanceActionPayload at the time when this specific
    #              payload is created as a child of it so that the
    #              instance.create notification using this new payload does not
    #              have decreasing version.
    #         1.3: Add keypairs field
    #         1.4: Add key_name field to InstancePayload
    #         1.5: Add BDM related data to InstancePayload
    #         1.6: Add tags field to InstanceCreatePayload
    #         1.7: Added updated_at field to InstancePayload
    VERSION = '1.7'

    fields = {
        'keypairs': fields.ListOfObjectsField('KeypairPayload'),
        'tags': fields.ListOfStringsField(),
    }

    def __init__(self, instance, fault, bdms):
        super(InstanceCreatePayload, self).__init__(
            instance=instance,
            fault=fault,
            bdms=bdms)
        self.keypairs = [keypair_payload.KeypairPayload(keypair=keypair)
                         for keypair in instance.keypairs]
        self.tags = [instance_tag.tag
                     for instance_tag in instance.tags]


@nova_base.NovaObjectRegistry.register_notification
class InstanceActionResizePrepPayload(InstanceActionPayload):
    # No SCHEMA as all the additional fields are calculated

    # Version 1.0: Initial version
    VERSION = '1.0'
    fields = {
        'new_flavor': fields.ObjectField('FlavorPayload', nullable=True)
    }

    def __init__(self, instance, fault, new_flavor):
        super(InstanceActionResizePrepPayload, self).__init__(
                instance=instance,
                fault=fault)
        self.new_flavor = new_flavor


@nova_base.NovaObjectRegistry.register_notification
class InstanceUpdatePayload(InstancePayload):
    # Version 1.0: Initial version
    # Version 1.1: locked and display_description added to InstancePayload
    # Version 1.2: Added tags field
    # Version 1.3: Added auto_disk_config field to InstancePayload
    # Version 1.4: Added key_name field to InstancePayload
    # Version 1.5: Add BDM related data
    # Version 1.6: Added updated_at field to InstancePayload
    VERSION = '1.6'
    fields = {
        'state_update': fields.ObjectField('InstanceStateUpdatePayload'),
        'audit_period': fields.ObjectField('AuditPeriodPayload'),
        'bandwidth': fields.ListOfObjectsField('BandwidthPayload'),
        'old_display_name': fields.StringField(nullable=True),
        'tags': fields.ListOfStringsField(),
    }

    def __init__(self, instance, state_update, audit_period, bandwidth,
                 old_display_name):
        super(InstanceUpdatePayload, self).__init__(instance=instance)
        self.state_update = state_update
        self.audit_period = audit_period
        self.bandwidth = bandwidth
        self.old_display_name = old_display_name
        self.tags = [instance_tag.tag
                     for instance_tag in instance.tags.objects]


@nova_base.NovaObjectRegistry.register_notification
class InstanceActionRescuePayload(InstanceActionPayload):
    # Version 1.0: Initial version
    VERSION = '1.0'
    fields = {
        'rescue_image_ref': fields.UUIDField(nullable=True)
    }

    def __init__(self, instance, fault, rescue_image_ref):
        super(InstanceActionRescuePayload, self).__init__(
                instance=instance,
                fault=fault)
        self.rescue_image_ref = rescue_image_ref


@nova_base.NovaObjectRegistry.register_notification
class IpPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'
    fields = {
        'label': fields.StringField(),
        'mac': fields.MACAddressField(),
        'meta': fields.DictOfStringsField(),
        'port_uuid': fields.UUIDField(nullable=True),
        'version': fields.IntegerField(),
        'address': fields.IPV4AndV6AddressField(),
        'device_name': fields.StringField(nullable=True)
    }

    def __init__(self, label, mac, meta, port_uuid, version, address,
                 device_name):
        super(IpPayload, self).__init__()
        self.label = label
        self.mac = mac
        self.meta = meta
        self.port_uuid = port_uuid
        self.version = version
        self.address = address
        self.device_name = device_name

    @classmethod
    def from_network_info(cls, network_info):
        """Returns a list of IpPayload object based on the passed
        network_info.
        """
        ips = []
        if network_info is not None:
            for vif in network_info:
                for ip in vif.fixed_ips():
                    ips.append(cls(
                        label=vif["network"]["label"],
                        mac=vif["address"],
                        meta=vif["meta"],
                        port_uuid=vif["id"],
                        version=ip["version"],
                        address=ip["address"],
                        device_name=vif["devname"]))
        return ips


@nova_base.NovaObjectRegistry.register_notification
class BandwidthPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'
    fields = {
        'network_name': fields.StringField(),
        'in_bytes': fields.IntegerField(),
        'out_bytes': fields.IntegerField(),
    }

    def __init__(self, network_name, in_bytes, out_bytes):
        super(BandwidthPayload, self).__init__()
        self.network_name = network_name
        self.in_bytes = in_bytes
        self.out_bytes = out_bytes


@nova_base.NovaObjectRegistry.register_notification
class AuditPeriodPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'
    fields = {
        'audit_period_beginning': fields.DateTimeField(),
        'audit_period_ending': fields.DateTimeField(),
    }

    def __init__(self, audit_period_beginning, audit_period_ending):
        super(AuditPeriodPayload, self).__init__()
        self.audit_period_beginning = audit_period_beginning
        self.audit_period_ending = audit_period_ending


@nova_base.NovaObjectRegistry.register_notification
class BlockDevicePayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    SCHEMA = {
        'device_name': ('bdm', 'device_name'),
        'boot_index': ('bdm', 'boot_index'),
        'delete_on_termination': ('bdm', 'delete_on_termination'),
        'volume_id': ('bdm', 'volume_id'),
        'tag': ('bdm', 'tag')
    }

    fields = {
        'device_name': fields.StringField(nullable=True),
        'boot_index': fields.IntegerField(nullable=True),
        'delete_on_termination': fields.BooleanField(default=False),
        'volume_id': fields.UUIDField(),
        'tag': fields.StringField(nullable=True)
    }

    def __init__(self, bdm):
        super(BlockDevicePayload, self).__init__()
        self.populate_schema(bdm=bdm)

    @classmethod
    def from_instance(cls, instance):
        """Returns a list of BlockDevicePayload objects based on the passed
        bdms.
        """
        if not CONF.notifications.bdms_in_notifications:
            return None

        instance_bdms = instance.get_bdms()
        if instance_bdms is not None:
            return cls.from_bdms(instance_bdms)
        else:
            return []

    @classmethod
    def from_bdms(cls, bdms):
        """Returns a list of BlockDevicePayload objects based on the passed
        BlockDeviceMappingList.
        """
        payloads = []
        for bdm in bdms:
            if bdm.volume_id is not None:
                payloads.append(cls(bdm))
        return payloads


@nova_base.NovaObjectRegistry.register_notification
class InstanceStateUpdatePayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'
    fields = {
        'old_state': fields.StringField(nullable=True),
        'state': fields.StringField(nullable=True),
        'old_task_state': fields.StringField(nullable=True),
        'new_task_state': fields.StringField(nullable=True),
    }

    def __init__(self, old_state, state, old_task_state, new_task_state):
        super(InstanceStateUpdatePayload, self).__init__()
        self.old_state = old_state
        self.state = state
        self.old_task_state = old_task_state
        self.new_task_state = new_task_state


@base.notification_sample('instance-delete-start.json')
@base.notification_sample('instance-delete-end.json')
@base.notification_sample('instance-pause-start.json')
@base.notification_sample('instance-pause-end.json')
@base.notification_sample('instance-unpause-start.json')
@base.notification_sample('instance-unpause-end.json')
@base.notification_sample('instance-resize-start.json')
@base.notification_sample('instance-resize-end.json')
@base.notification_sample('instance-resize-error.json')
@base.notification_sample('instance-suspend-start.json')
@base.notification_sample('instance-suspend-end.json')
@base.notification_sample('instance-power_on-start.json')
@base.notification_sample('instance-power_on-end.json')
@base.notification_sample('instance-power_off-start.json')
@base.notification_sample('instance-power_off-end.json')
@base.notification_sample('instance-reboot-start.json')
@base.notification_sample('instance-reboot-end.json')
@base.notification_sample('instance-reboot-error.json')
@base.notification_sample('instance-shutdown-start.json')
@base.notification_sample('instance-shutdown-end.json')
@base.notification_sample('instance-interface_attach-start.json')
@base.notification_sample('instance-interface_attach-end.json')
@base.notification_sample('instance-interface_attach-error.json')
@base.notification_sample('instance-shelve-start.json')
@base.notification_sample('instance-shelve-end.json')
@base.notification_sample('instance-resume-start.json')
@base.notification_sample('instance-resume-end.json')
@base.notification_sample('instance-restore-start.json')
@base.notification_sample('instance-restore-end.json')
@base.notification_sample('instance-evacuate.json')
@base.notification_sample('instance-resize_finish-start.json')
@base.notification_sample('instance-resize_finish-end.json')
@base.notification_sample('instance-live_migration_pre-start.json')
@base.notification_sample('instance-live_migration_pre-end.json')
@base.notification_sample('instance-live_migration_abort-start.json')
@base.notification_sample('instance-live_migration_abort-end.json')
# @base.notification_sample('instance-live_migration_post-start.json')
# @base.notification_sample('instance-live_migration_post-end.json')
# @base.notification_sample('instance-live_migration_post_dest-start.json')
# @base.notification_sample('instance-live_migration_post_dest-end.json')
@base.notification_sample('instance-live_migration_rollback-start.json')
@base.notification_sample('instance-live_migration_rollback-end.json')
# @base.notification_sample('instance-live_migration_rollback_dest-start.json')
# @base.notification_sample('instance-live_migration_rollback_dest-end.json')
@base.notification_sample('instance-rebuild-start.json')
@base.notification_sample('instance-rebuild-end.json')
@base.notification_sample('instance-rebuild-error.json')
@base.notification_sample('instance-interface_detach-start.json')
@base.notification_sample('instance-interface_detach-end.json')
@base.notification_sample('instance-resize_confirm-start.json')
@base.notification_sample('instance-resize_confirm-end.json')
@base.notification_sample('instance-resize_revert-start.json')
@base.notification_sample('instance-resize_revert-end.json')
@base.notification_sample('instance-shelve_offload-start.json')
@base.notification_sample('instance-shelve_offload-end.json')
@base.notification_sample('instance-soft_delete-start.json')
@base.notification_sample('instance-soft_delete-end.json')
@base.notification_sample('instance-trigger_crash_dump-start.json')
@base.notification_sample('instance-trigger_crash_dump-end.json')
@base.notification_sample('instance-unrescue-start.json')
@base.notification_sample('instance-unrescue-end.json')
@base.notification_sample('instance-unshelve-start.json')
@base.notification_sample('instance-unshelve-end.json')
@nova_base.NovaObjectRegistry.register_notification
class InstanceActionNotification(base.NotificationBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': fields.ObjectField('InstanceActionPayload')
    }


@base.notification_sample('instance-update.json')
@nova_base.NovaObjectRegistry.register_notification
class InstanceUpdateNotification(base.NotificationBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': fields.ObjectField('InstanceUpdatePayload')
    }


@base.notification_sample('instance-volume_swap-start.json')
@base.notification_sample('instance-volume_swap-end.json')
@base.notification_sample('instance-volume_swap-error.json')
@nova_base.NovaObjectRegistry.register_notification
class InstanceActionVolumeSwapNotification(base.NotificationBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': fields.ObjectField('InstanceActionVolumeSwapPayload')
    }


@base.notification_sample('instance-volume_attach-start.json')
@base.notification_sample('instance-volume_attach-end.json')
@base.notification_sample('instance-volume_attach-error.json')
@base.notification_sample('instance-volume_detach-start.json')
@base.notification_sample('instance-volume_detach-end.json')
@nova_base.NovaObjectRegistry.register_notification
class InstanceActionVolumeNotification(base.NotificationBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': fields.ObjectField('InstanceActionVolumePayload')
    }


@base.notification_sample('instance-create-start.json')
@base.notification_sample('instance-create-end.json')
@base.notification_sample('instance-create-error.json')
@nova_base.NovaObjectRegistry.register_notification
class InstanceCreateNotification(base.NotificationBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': fields.ObjectField('InstanceCreatePayload')
    }


@base.notification_sample('instance-resize_prep-start.json')
@base.notification_sample('instance-resize_prep-end.json')
@nova_base.NovaObjectRegistry.register_notification
class InstanceActionResizePrepNotification(base.NotificationBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': fields.ObjectField('InstanceActionResizePrepPayload')
    }


@base.notification_sample('instance-snapshot-start.json')
@base.notification_sample('instance-snapshot-end.json')
@nova_base.NovaObjectRegistry.register_notification
class InstanceActionSnapshotNotification(base.NotificationBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': fields.ObjectField('InstanceActionSnapshotPayload')
    }


@base.notification_sample('instance-rescue-start.json')
@base.notification_sample('instance-rescue-end.json')
@nova_base.NovaObjectRegistry.register_notification
class InstanceActionRescueNotification(base.NotificationBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': fields.ObjectField('InstanceActionRescuePayload')
    }


@nova_base.NovaObjectRegistry.register_notification
class InstanceActionSnapshotPayload(InstanceActionPayload):
    # Version 1.6: Initial version. It starts at version 1.6 as
    #              instance.snapshot.start and .end notifications are switched
    #              from using InstanceActionPayload 1.5 to this new payload and
    #              also it added a new field so we wanted to keep the version
    #              number increasing to signal the change.
    VERSION = '1.6'
    fields = {
        'snapshot_image_id': fields.UUIDField(),
    }

    def __init__(self, instance, fault, snapshot_image_id):
        super(InstanceActionSnapshotPayload, self).__init__(
                instance=instance,
                fault=fault)
        self.snapshot_image_id = snapshot_image_id
