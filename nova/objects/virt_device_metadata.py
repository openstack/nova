# Copyright (C) 2016, Red Hat, Inc.
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

from oslo_serialization import jsonutils
from oslo_utils import versionutils

from nova import db
from nova.objects import base
from nova.objects import fields


@base.NovaObjectRegistry.register
class DeviceBus(base.NovaObject):
    VERSION = '1.0'


@base.NovaObjectRegistry.register
class PCIDeviceBus(DeviceBus):
    VERSION = '1.0'

    fields = {
        'address': fields.PCIAddressField(),
    }


@base.NovaObjectRegistry.register
class USBDeviceBus(DeviceBus):
    VERSION = '1.0'

    fields = {
        'address': fields.USBAddressField(),
    }


@base.NovaObjectRegistry.register
class SCSIDeviceBus(DeviceBus):
    VERSION = '1.0'

    fields = {
        'address': fields.SCSIAddressField(),
    }


@base.NovaObjectRegistry.register
class IDEDeviceBus(DeviceBus):
    VERSION = '1.0'

    fields = {
        'address': fields.IDEAddressField(),
    }


@base.NovaObjectRegistry.register
class XenDeviceBus(DeviceBus):
    VERSION = '1.0'

    fields = {
        'address': fields.XenAddressField(),
    }


@base.NovaObjectRegistry.register
class DeviceMetadata(base.NovaObject):
    VERSION = '1.0'

    fields = {
        'bus': fields.ObjectField("DeviceBus", subclasses=True),
        'tags': fields.ListOfStringsField(),
    }


@base.NovaObjectRegistry.register
class NetworkInterfaceMetadata(DeviceMetadata):
    # Version 1.0: Initial version
    # Version 1.1: Add vlans field
    VERSION = '1.1'

    fields = {
        'mac': fields.MACAddressField(),
        'vlan': fields.IntegerField(),
    }

    def obj_make_compatible(self, primitive, target_version):
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 1) and 'vlan' in primitive:
            del primitive['vlan']


@base.NovaObjectRegistry.register
class DiskMetadata(DeviceMetadata):
    VERSION = '1.0'

    fields = {
        'serial': fields.StringField(nullable=True),
        'path': fields.StringField(nullable=True),
    }


@base.NovaObjectRegistry.register
class InstanceDeviceMetadata(base.NovaObject):
    VERSION = '1.0'
    fields = {
        'devices': fields.ListOfObjectsField('DeviceMetadata',
                                             subclasses=True),
    }

    @classmethod
    def obj_from_db(cls, context, db_dev_meta):
        primitive = jsonutils.loads(db_dev_meta)
        device_metadata = cls.obj_from_primitive(primitive)
        return device_metadata

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        db_extra = db.instance_extra_get_by_instance_uuid(
                context, instance_uuid, columns=['device_metadata'])
        if not db_extra or db_extra['device_metadata'] is None:
            return None

        primitive = jsonutils.loads(db_extra['device_metadata'])
        device_metadata = cls.obj_from_primitive(primitive)
        return device_metadata

    def _to_json(self):
        return jsonutils.dumps(self.obj_to_primitive())
