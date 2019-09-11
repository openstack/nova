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

from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import versionutils

from nova.db import api as db
from nova import exception
from nova.objects import base
from nova.objects import fields

LOG = logging.getLogger(__name__)


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
    # Version 1.2: Add old/new resources
    VERSION = '1.2'

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
        'new_resources': fields.ObjectField('ResourceList',
                                            nullable=True),
        'old_resources': fields.ObjectField('ResourceList',
                                            nullable=True),
    }

    @classmethod
    def obj_make_compatible(cls, primitive, target_version):
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 2):
            primitive.pop('old_resources', None)
            primitive.pop('new_resources', None)
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

    def get_pci_mapping_for_migration(self, revert):
        """Get the mapping between the old PCI devices and the new PCI
        devices that have been allocated during this migration.  The
        correlation is based on PCI request ID which is unique per PCI
        devices for SR-IOV ports.

        :param revert: If True, return a reverse mapping i.e
               mapping between new PCI devices and old PCI devices.
        :returns: dictionary of PCI mapping.
                  if revert==False:
                      {'<old pci address>': <New PciDevice>}
                  if revert==True:
                      {'<new pci address>': <Old PciDevice>}
        """
        step = -1 if revert else 1
        current_pci_devs, updated_pci_devs = (self.old_pci_devices,
                                              self.new_pci_devices)[::step]
        if current_pci_devs and updated_pci_devs:
            LOG.debug("Determining PCI devices mapping using migration "
                      "context: current_pci_devs: %(cur)s, "
                      "updated_pci_devs: %(upd)s",
                      {'cur': [dev for dev in current_pci_devs],
                       'upd': [dev for dev in updated_pci_devs]})
            return {curr_dev.address: upd_dev
                    for curr_dev in current_pci_devs
                        for upd_dev in updated_pci_devs
                            if curr_dev.request_id == upd_dev.request_id}
        return {}
