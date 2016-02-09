# Copyright 2013 Intel Corporation
# All Rights Reserved.
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

import copy

from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import versionutils

from nova import context
from nova import db
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields

LOG = logging.getLogger(__name__)


def compare_pci_device_attributes(obj_a, obj_b):
    pci_ignore_fields = base.NovaPersistentObject.fields.keys()
    for name in obj_a.obj_fields:
        if name in pci_ignore_fields:
            continue
        is_set_a = obj_a.obj_attr_is_set(name)
        is_set_b = obj_b.obj_attr_is_set(name)
        if is_set_a != is_set_b:
            return False
        if is_set_a:
            if getattr(obj_a, name) != getattr(obj_b, name):
                return False
    return True


@base.NovaObjectRegistry.register
class PciDevice(base.NovaPersistentObject, base.NovaObject):

    """Object to represent a PCI device on a compute node.

    PCI devices are managed by the compute resource tracker, which discovers
    the devices from the hardware platform, claims, allocates and frees
    devices for instances.

    The PCI device information is permanently maintained in a database.
    This makes it convenient to get PCI device information, like physical
    function for a VF device, adjacent switch IP address for a NIC,
    hypervisor identification for a PCI device, etc. It also provides a
    convenient way to check device allocation information for administrator
    purposes.

    A device can be in available/claimed/allocated/deleted/removed state.

    A device is available when it is discovered..

    A device is claimed prior to being allocated to an instance. Normally the
    transition from claimed to allocated is quick. However, during a resize
    operation the transition can take longer, because devices are claimed in
    prep_resize and allocated in finish_resize.

    A device becomes removed when hot removed from a node (i.e. not found in
    the next auto-discover) but not yet synced with the DB. A removed device
    should not be allocated to any instance, and once deleted from the DB,
    the device object is changed to deleted state and no longer synced with
    the DB.

    Filed notes::

        | 'dev_id':
        |   Hypervisor's identification for the device, the string format
        |   is hypervisor specific
        | 'extra_info':
        |   Device-specific properties like PF address, switch ip address etc.

    """

    # Version 1.0: Initial version
    # Version 1.1: String attributes updated to support unicode
    # Version 1.2: added request_id field
    # Version 1.3: Added field to represent PCI device NUMA node
    # Version 1.4: Added parent_addr field
    # Version 1.5: Added 2 new device statuses: UNCLAIMABLE and UNAVAILABLE
    VERSION = '1.5'

    fields = {
        'id': fields.IntegerField(),
        # Note(yjiang5): the compute_node_id may be None because the pci
        # device objects are created before the compute node is created in DB
        'compute_node_id': fields.IntegerField(nullable=True),
        'address': fields.StringField(),
        'vendor_id': fields.StringField(),
        'product_id': fields.StringField(),
        'dev_type': fields.PciDeviceTypeField(),
        'status': fields.PciDeviceStatusField(),
        'dev_id': fields.StringField(nullable=True),
        'label': fields.StringField(nullable=True),
        'instance_uuid': fields.StringField(nullable=True),
        'request_id': fields.StringField(nullable=True),
        'extra_info': fields.DictOfStringsField(),
        'numa_node': fields.IntegerField(nullable=True),
        'parent_addr': fields.StringField(nullable=True),
    }

    @staticmethod
    def should_migrate_data():
        # NOTE(ndipanov): Only migrate parent_addr if all services are up to at
        # least version 4 - this should only ever be called from save()
        services = ('conductor', 'api')
        min_parent_addr_version = 4

        min_deployed = min(objects.Service.get_minimum_version(
            context.get_admin_context(), 'nova-' + service)
            for service in services)
        return min_deployed >= min_parent_addr_version

    def obj_make_compatible(self, primitive, target_version):
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 2) and 'request_id' in primitive:
            del primitive['request_id']
        if target_version < (1, 4) and 'parent_addr' in primitive:
            if primitive['parent_addr'] is not None:
                extra_info = primitive.get('extra_info', {})
                extra_info['phys_function'] = primitive['parent_addr']
            del primitive['parent_addr']
        if target_version < (1, 5) and 'parent_addr' in primitive:
            added_statuses = (fields.PciDeviceStatus.UNCLAIMABLE,
                              fields.PciDeviceStatus.UNAVAILABLE)
            status = primitive['status']
            if status in added_statuses:
                raise exception.ObjectActionError(
                    action='obj_make_compatible',
                    reason='status=%s not supported in version %s' % (
                        status, target_version))

    def update_device(self, dev_dict):
        """Sync the content from device dictionary to device object.

        The resource tracker updates the available devices periodically.
        To avoid meaningless syncs with the database, we update the device
        object only if a value changed.
        """

        # Note(yjiang5): status/instance_uuid should only be updated by
        # functions like claim/allocate etc. The id is allocated by
        # database. The extra_info is created by the object.
        no_changes = ('status', 'instance_uuid', 'id', 'extra_info')
        map(lambda x: dev_dict.pop(x, None),
            [key for key in no_changes])

        # NOTE(ndipanov): This needs to be set as it's accessed when matching
        dev_dict.setdefault('parent_addr')

        for k, v in dev_dict.items():
            if k in self.fields.keys():
                setattr(self, k, v)
            else:
                # Note (yjiang5) extra_info.update does not update
                # obj_what_changed, set it explicitly
                extra_info = self.extra_info
                extra_info.update({k: v})
                self.extra_info = extra_info

    def __init__(self, *args, **kwargs):
        super(PciDevice, self).__init__(*args, **kwargs)
        self.obj_reset_changes()
        self.extra_info = {}

    def __eq__(self, other):
        return compare_pci_device_attributes(self, other)

    def __ne__(self, other):
        return not (self == other)

    @staticmethod
    def _from_db_object(context, pci_device, db_dev):
        for key in pci_device.fields:
            if key != 'extra_info':
                setattr(pci_device, key, db_dev[key])
            else:
                extra_info = db_dev.get("extra_info")
                pci_device.extra_info = jsonutils.loads(extra_info)
        pci_device._context = context
        pci_device.obj_reset_changes()
        # NOTE(ndipanov): As long as there is PF data in the old location, we
        # want to load it as it may have be the only place we have it
        if 'phys_function' in pci_device.extra_info:
            pci_device.parent_addr = pci_device.extra_info['phys_function']

        return pci_device

    @base.remotable_classmethod
    def get_by_dev_addr(cls, context, compute_node_id, dev_addr):
        db_dev = db.pci_device_get_by_addr(
            context, compute_node_id, dev_addr)
        return cls._from_db_object(context, cls(), db_dev)

    @base.remotable_classmethod
    def get_by_dev_id(cls, context, id):
        db_dev = db.pci_device_get_by_id(context, id)
        return cls._from_db_object(context, cls(), db_dev)

    @classmethod
    def create(cls, context, dev_dict):
        """Create a PCI device based on hypervisor information.

        As the device object is just created and is not synced with db yet
        thus we should not reset changes here for fields from dict.
        """
        pci_device = cls()
        pci_device.update_device(dev_dict)
        pci_device.status = fields.PciDeviceStatus.AVAILABLE
        pci_device._context = context
        return pci_device

    @base.remotable
    def save(self):
        if self.status == fields.PciDeviceStatus.REMOVED:
            self.status = fields.PciDeviceStatus.DELETED
            db.pci_device_destroy(self._context, self.compute_node_id,
                                  self.address)
        elif self.status != fields.PciDeviceStatus.DELETED:
            updates = self.obj_get_changes()
            if not self.should_migrate_data():
                # NOTE(ndipanov): If we are not migrating data yet, make sure
                # that any changes to parent_addr are also in the old location
                # in extra_info
                if 'parent_addr' in updates and updates['parent_addr']:
                    extra_update = updates.get('extra_info', {})
                    if not extra_update and self.obj_attr_is_set('extra_info'):
                        extra_update = self.extra_info
                    extra_update['phys_function'] = updates['parent_addr']
                    updates['extra_info'] = extra_update
            else:
                # NOTE(ndipanov): Once we start migrating, meaning all control
                # plane has been upgraded - aggressively migrate on every save
                pf_extra = self.extra_info.pop('phys_function', None)
                if pf_extra and 'parent_addr' not in updates:
                    updates['parent_addr'] = pf_extra
                updates['extra_info'] = self.extra_info

            if 'extra_info' in updates:
                updates['extra_info'] = jsonutils.dumps(updates['extra_info'])
            if updates:
                db_pci = db.pci_device_update(self._context,
                                              self.compute_node_id,
                                              self.address, updates)
                self._from_db_object(self._context, self, db_pci)

    @staticmethod
    def _bulk_update_status(dev_list, status):
        for dev in dev_list:
            dev.status = status

    def claim(self, instance):
        if self.status != fields.PciDeviceStatus.AVAILABLE:
            raise exception.PciDeviceInvalidStatus(
                compute_node_id=self.compute_node_id,
                address=self.address, status=self.status,
                hopestatus=[fields.PciDeviceStatus.AVAILABLE])

        if self.dev_type == fields.PciDeviceType.SRIOV_PF:
            # Update PF status to CLAIMED if all of it dependants are free
            # and set their status to UNCLAIMABLE
            vfs_list = objects.PciDeviceList.get_by_parent_address(
                                             self._context,
                                             self.compute_node_id,
                                             self.address)
            if not all([vf.is_available() for vf in vfs_list]):
                raise exception.PciDeviceVFInvalidStatus(
                    compute_node_id=self.compute_node_id,
                    address=self.address)
            self._bulk_update_status(vfs_list,
                                           fields.PciDeviceStatus.UNCLAIMABLE)

        elif self.dev_type == fields.PciDeviceType.SRIOV_VF:
            # Update VF status to CLAIMED if it's parent has not been
            # previuosly allocated or claimed
            # When claiming/allocating a VF, it's parent PF becomes
            # unclaimable/unavailable. Therefore, it is expected to find the
            # parent PF in an unclaimable/unavailable state for any following
            # claims to a sibling VF

            parent_ok_statuses = (fields.PciDeviceStatus.AVAILABLE,
                                  fields.PciDeviceStatus.UNCLAIMABLE,
                                  fields.PciDeviceStatus.UNAVAILABLE)
            try:
                parent = self.get_by_dev_addr(self._context,
                                              self.compute_node_id,
                                              self.parent_addr)
                if parent.status not in parent_ok_statuses:
                    raise exception.PciDevicePFInvalidStatus(
                        compute_node_id=self.compute_node_id,
                        address=self.parent_addr, status=self.status,
                        vf_address=self.address,
                        hopestatus=parent_ok_statuses)
                # Set PF status
                if parent.status == fields.PciDeviceStatus.AVAILABLE:
                    parent.status = fields.PciDeviceStatus.UNCLAIMABLE
            except exception.PciDeviceNotFound:
                LOG.debug('Physical function addr: %(pf_addr)s parent of '
                          'VF addr: %(vf_addr)s was not found',
                           {'pf_addr': self.parent_addr,
                            'vf_addr': self.address})

        self.status = fields.PciDeviceStatus.CLAIMED
        self.instance_uuid = instance['uuid']

    def allocate(self, instance):
        ok_statuses = (fields.PciDeviceStatus.AVAILABLE,
                       fields.PciDeviceStatus.CLAIMED)
        parent_ok_statuses = (fields.PciDeviceStatus.AVAILABLE,
                              fields.PciDeviceStatus.UNCLAIMABLE,
                              fields.PciDeviceStatus.UNAVAILABLE)
        dependatns_ok_statuses = (fields.PciDeviceStatus.AVAILABLE,
                                  fields.PciDeviceStatus.UNCLAIMABLE)
        if self.status not in ok_statuses:
            raise exception.PciDeviceInvalidStatus(
                compute_node_id=self.compute_node_id,
                address=self.address, status=self.status,
                hopestatus=ok_statuses)
        if (self.status == fields.PciDeviceStatus.CLAIMED and
                self.instance_uuid != instance['uuid']):
            raise exception.PciDeviceInvalidOwner(
                compute_node_id=self.compute_node_id,
                address=self.address, owner=self.instance_uuid,
                hopeowner=instance['uuid'])
        if self.dev_type == fields.PciDeviceType.SRIOV_PF:
            vfs_list = objects.PciDeviceList.get_by_parent_address(
                                             self._context,
                                             self.compute_node_id,
                                             self.address)
            if not all([vf.status in dependatns_ok_statuses for
                        vf in vfs_list]):
                raise exception.PciDeviceVFInvalidStatus(
                    compute_node_id=self.compute_node_id,
                    address=self.address)
            self._bulk_update_status(vfs_list,
                                     fields.PciDeviceStatus.UNAVAILABLE)

        elif (self.dev_type == fields.PciDeviceType.SRIOV_VF):
            try:
                parent = self.get_by_dev_addr(self._context,
                                              self.compute_node_id,
                                              self.parent_addr)
                if parent.status not in parent_ok_statuses:
                    raise exception.PciDevicePFInvalidStatus(
                        compute_node_id=self.compute_node_id,
                        address=self.parent_addr, status=self.status,
                        vf_address=self.address,
                        hopestatus=parent_ok_statuses)
                # Set PF status
                parent.status = fields.PciDeviceStatus.UNAVAILABLE
            except exception.PciDeviceNotFound:
                LOG.debug('Physical function addr: %(pf_addr)s parent of '
                          'VF addr: %(vf_addr)s was not found',
                           {'pf_addr': self.parent_addr,
                            'vf_addr': self.address})

        self.status = fields.PciDeviceStatus.ALLOCATED
        self.instance_uuid = instance['uuid']

        # Notes(yjiang5): remove this check when instance object for
        # compute manager is finished
        if isinstance(instance, dict):
            if 'pci_devices' not in instance:
                instance['pci_devices'] = []
            instance['pci_devices'].append(copy.copy(self))
        else:
            instance.pci_devices.objects.append(copy.copy(self))

    def remove(self):
        if self.status != fields.PciDeviceStatus.AVAILABLE:
            raise exception.PciDeviceInvalidStatus(
                compute_node_id=self.compute_node_id,
                address=self.address, status=self.status,
                hopestatus=[fields.PciDeviceStatus.AVAILABLE])
        self.status = fields.PciDeviceStatus.REMOVED
        self.instance_uuid = None
        self.request_id = None

    def free(self, instance=None):
        ok_statuses = (fields.PciDeviceStatus.ALLOCATED,
                       fields.PciDeviceStatus.CLAIMED)
        free_devs = []
        if self.status not in ok_statuses:
            raise exception.PciDeviceInvalidStatus(
                compute_node_id=self.compute_node_id,
                address=self.address, status=self.status,
                hopestatus=ok_statuses)
        if instance and self.instance_uuid != instance['uuid']:
            raise exception.PciDeviceInvalidOwner(
                compute_node_id=self.compute_node_id,
                address=self.address, owner=self.instance_uuid,
                hopeowner=instance['uuid'])
        if self.dev_type == fields.PciDeviceType.SRIOV_PF:
            # Set all PF dependants status to AVAILABLE
            vfs_list = objects.PciDeviceList.get_by_parent_address(
                                             self._context,
                                             self.compute_node_id,
                                             self.address)
            self._bulk_update_status(vfs_list,
                                     fields.PciDeviceStatus.AVAILABLE)
            free_devs.extend(vfs_list)
        if self.dev_type == fields.PciDeviceType.SRIOV_VF:
            # Set PF status to AVAILABLE if all of it's VFs are free
            vfs_list = objects.PciDeviceList.get_by_parent_address(
                                             self._context,
                                             self.compute_node_id,
                                             self.parent_addr)
            if all([vf.is_available() for vf in vfs_list if vf.id != self.id]):
                try:
                    parent = self.get_by_dev_addr(self._context,
                                                  self.compute_node_id,
                                                  self.parent_addr)
                    parent.status = fields.PciDeviceStatus.AVAILABLE
                    free_devs.append(parent)
                except exception.PciDeviceNotFound:
                    LOG.debug('Physical function addr: %(pf_addr)s parent of '
                              'VF addr: %(vf_addr)s was not found',
                               {'pf_addr': self.parent_addr,
                                'vf_addr': self.address})
        old_status = self.status
        self.status = fields.PciDeviceStatus.AVAILABLE
        free_devs.append(self)
        self.instance_uuid = None
        self.request_id = None
        if old_status == fields.PciDeviceStatus.ALLOCATED and instance:
            # Notes(yjiang5): remove this check when instance object for
            # compute manager is finished
            existed = next((dev for dev in instance['pci_devices']
                if dev.id == self.id))
            if isinstance(instance, dict):
                instance['pci_devices'].remove(existed)
            else:
                instance.pci_devices.objects.remove(existed)
        return free_devs

    def is_available(self):
        return self.status == fields.PciDeviceStatus.AVAILABLE


@base.NovaObjectRegistry.register
class PciDeviceList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    #              PciDevice <= 1.1
    # Version 1.1: PciDevice 1.2
    # Version 1.2: PciDevice 1.3
    # Version 1.3: Adds get_by_parent_address
    VERSION = '1.3'

    fields = {
        'objects': fields.ListOfObjectsField('PciDevice'),
        }

    def __init__(self, *args, **kwargs):
        super(PciDeviceList, self).__init__(*args, **kwargs)
        self.objects = []
        self.obj_reset_changes()

    @base.remotable_classmethod
    def get_by_compute_node(cls, context, node_id):
        db_dev_list = db.pci_device_get_all_by_node(context, node_id)
        return base.obj_make_list(context, cls(context), objects.PciDevice,
                                  db_dev_list)

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, uuid):
        db_dev_list = db.pci_device_get_all_by_instance_uuid(context, uuid)
        return base.obj_make_list(context, cls(context), objects.PciDevice,
                                  db_dev_list)

    @base.remotable_classmethod
    def get_by_parent_address(cls, context, node_id, parent_addr):
        db_dev_list = db.pci_device_get_all_by_parent_addr(context,
                                                           node_id,
                                                           parent_addr)
        return base.obj_make_list(context, cls(context), objects.PciDevice,
                                  db_dev_list)
