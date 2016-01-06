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


from nova.objects import base
from nova.objects import fields


@base.NovaObjectRegistry.register_if(False)
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
class DeviceMetadata(base.NovaObject):
    VERSION = '1.0'

    fields = {
        'bus': fields.ObjectField("DeviceBus", subclasses=True),
        'tags': fields.ListOfStringsField(),
    }


@base.NovaObjectRegistry.register
class NetworkInterfaceMetadata(DeviceMetadata):
    VERSION = '1.0'

    fields = {
        'mac': fields.MACAddressField(),
    }


@base.NovaObjectRegistry.register
class DiskMetadata(DeviceMetadata):
    VERSION = '1.0'

    fields = {
        'serial': fields.StringField(nullable=True),
        'path': fields.StringField(nullable=True),
    }


@base.NovaObjectRegistry.register
class DeviceMetadataList(base.ObjectListBase, base.NovaObject):
    VERSION = '1.0'
    fields = {
        'objects': fields.ListOfObjectsField('DeviceMetadata',
                                             subclasses=True),
    }
