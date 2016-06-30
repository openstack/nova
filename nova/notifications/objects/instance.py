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
class InstancePayload(base.NotificationPayloadBase):
    SCHEMA = {
        'uuid': ('instance', 'uuid'),
        'user_id': ('instance', 'user_id'),
        'tenant_id': ('instance', 'project_id'),
        'reservation_id': ('instance', 'reservation_id'),
        'display_name': ('instance', 'display_name'),
        'host_name': ('instance', 'hostname'),
        'host': ('instance', 'host'),
        'node': ('instance', 'node'),
        'os_type': ('instance', 'os_type'),
        'architecture': ('instance', 'architecture'),
        'availability_zone': ('instance', 'availability_zone'),

        'image_uuid': ('instance', 'image_ref'),

        'kernel_id': ('instance', 'kernel_id'),
        'ramdisk_id': ('instance', 'ramdisk_id'),

        'created_at': ('instance', 'created_at'),
        'launched_at': ('instance', 'launched_at'),
        'terminated_at': ('instance', 'terminated_at'),
        'deleted_at': ('instance', 'deleted_at'),

        'state': ('instance', 'vm_state'),
        'power_state': ('instance', 'power_state'),
        'task_state': ('instance', 'task_state'),
        'progress': ('instance', 'progress'),

        'metadata': ('instance', 'metadata'),
    }
    # Version 1.0: Initial version
    VERSION = '1.0'
    fields = {
        'uuid': fields.UUIDField(),
        'user_id': fields.StringField(nullable=True),
        'tenant_id': fields.StringField(nullable=True),
        'reservation_id': fields.StringField(nullable=True),
        'display_name': fields.StringField(nullable=True),
        'host_name': fields.StringField(nullable=True),
        'host': fields.StringField(nullable=True),
        'node': fields.StringField(nullable=True),
        'os_type': fields.StringField(nullable=True),
        'architecture': fields.StringField(nullable=True),
        'availability_zone': fields.StringField(nullable=True),

        'flavor': fields.ObjectField('FlavorPayload'),
        'image_uuid': fields.StringField(nullable=True),

        'kernel_id': fields.StringField(nullable=True),
        'ramdisk_id': fields.StringField(nullable=True),

        'created_at': fields.DateTimeField(nullable=True),
        'launched_at': fields.DateTimeField(nullable=True),
        'terminated_at': fields.DateTimeField(nullable=True),
        'deleted_at': fields.DateTimeField(nullable=True),

        'state': fields.InstanceStateField(nullable=True),
        'power_state': fields.InstancePowerStateField(nullable=True),
        'task_state': fields.InstanceTaskStateField(nullable=True),
        'progress': fields.IntegerField(nullable=True),

        'ip_addresses': fields.ListOfObjectsField('IpPayload'),

        'metadata': fields.DictOfStringsField(),
    }

    def __init__(self, instance, **kwargs):
        super(InstancePayload, self).__init__(**kwargs)
        self.populate_schema(instance=instance)


@nova_base.NovaObjectRegistry.register_notification
class InstanceActionPayload(InstancePayload):
    # No SCHEMA as all the additional fields are calculated

    VERSION = '1.0'
    fields = {
        'fault': fields.ObjectField('ExceptionPayload', nullable=True),
    }

    def __init__(self, instance, fault, ip_addresses, flavor):
        super(InstanceActionPayload, self).__init__(
                instance=instance,
                fault=fault,
                ip_addresses=ip_addresses,
                flavor=flavor)


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


@nova_base.NovaObjectRegistry.register_notification
class FlavorPayload(base.NotificationPayloadBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    SCHEMA = {
        'flavorid': ('flavor', 'flavorid'),
        'memory_mb': ('instance', 'memory_mb'),
        'vcpus': ('instance', 'vcpus'),
        'root_gb': ('instance', 'root_gb'),
        'ephemeral_gb': ('instance', 'ephemeral_gb'),
    }

    fields = {
        'flavorid': fields.StringField(nullable=True),
        'memory_mb': fields.IntegerField(nullable=True),
        'vcpus': fields.IntegerField(nullable=True),
        'root_gb': fields.IntegerField(nullable=True),
        'ephemeral_gb': fields.IntegerField(nullable=True),
    }

    def __init__(self, instance, **kwargs):
        super(FlavorPayload, self).__init__(**kwargs)
        self.populate_schema(instance=instance, flavor=instance.flavor)


@base.notification_sample('instance-delete-start.json')
@base.notification_sample('instance-delete-end.json')
@nova_base.NovaObjectRegistry.register_notification
class InstanceActionNotification(base.NotificationBase):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'payload': fields.ObjectField('InstanceActionPayload')
    }
