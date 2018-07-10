#    Copyright 2015 Red Hat Inc.
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

from nova.db import api as db
from nova import exception
from nova.objects import base
from nova.objects import fields


@base.NovaObjectRegistry.register
class MigrationContext(base.NovaPersistentObject, base.NovaObject):
    """Data representing additional resources related to a migration.

    Some resources cannot be calculated from knowing the flavor alone for the
    purpose of resources tracking, but need to be persisted at the time the
    claim was made, for subsequent resource tracking runs to be consistent.
    MigrationContext objects are created when the claim is done and are there
    to facilitate resource tracking and final provisioning of the instance on
    the destination host.
    """

    # Version 1.0: Initial version
    # Version 1.1: Add old/new pci_devices and pci_requests
    VERSION = '1.1'

    fields = {
        'instance_uuid': fields.UUIDField(),
        'migration_id': fields.IntegerField(),
        'new_numa_topology': fields.ObjectField('InstanceNUMATopology',
                                                nullable=True),
        'old_numa_topology': fields.ObjectField('InstanceNUMATopology',
                                                nullable=True),
        'new_pci_devices': fields.ObjectField('PciDeviceList',
                                              nullable=True),
        'old_pci_devices': fields.ObjectField('PciDeviceList',
                                              nullable=True),
        'new_pci_requests': fields.ObjectField('InstancePCIRequests',
                                               nullable=True),
        'old_pci_requests': fields.ObjectField('InstancePCIRequests',
                                                nullable=True),
    }

    @classmethod
    def obj_make_compatible(cls, primitive, target_version):
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 1):
            primitive.pop('old_pci_devices', None)
            primitive.pop('new_pci_devices', None)
            primitive.pop('old_pci_requests', None)
            primitive.pop('new_pci_requests', None)

    @classmethod
    def obj_from_db_obj(cls, db_obj):
        primitive = jsonutils.loads(db_obj)
        return cls.obj_from_primitive(primitive)

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        db_extra = db.instance_extra_get_by_instance_uuid(
                context, instance_uuid, columns=['migration_context'])
        if not db_extra:
            raise exception.MigrationContextNotFound(
                instance_uuid=instance_uuid)

        if db_extra['migration_context'] is None:
            return None

        return cls.obj_from_db_obj(db_extra['migration_context'])
