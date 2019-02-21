# Copyright (C) 2014, Red Hat, Inc.
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
from oslo_utils import versionutils

from nova import context as nova_context
from nova.db import api as db
from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import models
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields

LOG = logging.getLogger(__name__)

VIF_OPTIONAL_FIELDS = ['network_id']
FAKE_UUID = '00000000-0000-0000-0000-000000000000'


@base.NovaObjectRegistry.register
class VirtualInterface(base.NovaPersistentObject, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Add tag field
    # Version 1.2: Adding a save method
    # Version 1.3: Added destroy() method
    VERSION = '1.3'

    fields = {
        'id': fields.IntegerField(),
        # This is a MAC address.
        'address': fields.StringField(nullable=True),
        'network_id': fields.IntegerField(),
        'instance_uuid': fields.UUIDField(),
        'uuid': fields.UUIDField(),
        'tag': fields.StringField(nullable=True),
    }

    def obj_make_compatible(self, primitive, target_version):
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 1) and 'tag' in primitive:
            del primitive['tag']

    @staticmethod
    def _from_db_object(context, vif, db_vif):
        for field in vif.fields:
            if not db_vif[field] and field in VIF_OPTIONAL_FIELDS:
                continue
            else:
                setattr(vif, field, db_vif[field])
        # NOTE(danms): The neutronv2 module namespaces mac addresses
        # with port id to avoid uniqueness constraints currently on
        # our table. Strip that out here so nobody else needs to care.
        if 'address' in vif and '/' in vif.address:
            vif.address, _ = vif.address.split('/', 1)
        vif._context = context
        vif.obj_reset_changes()
        return vif

    @base.remotable_classmethod
    def get_by_id(cls, context, vif_id):
        db_vif = db.virtual_interface_get(context, vif_id)
        if db_vif:
            return cls._from_db_object(context, cls(), db_vif)

    @base.remotable_classmethod
    def get_by_uuid(cls, context, vif_uuid):
        db_vif = db.virtual_interface_get_by_uuid(context, vif_uuid)
        if db_vif:
            return cls._from_db_object(context, cls(), db_vif)

    @base.remotable_classmethod
    def get_by_address(cls, context, address):
        db_vif = db.virtual_interface_get_by_address(context, address)
        if db_vif:
            return cls._from_db_object(context, cls(), db_vif)

    @base.remotable_classmethod
    def get_by_instance_and_network(cls, context, instance_uuid, network_id):
        db_vif = db.virtual_interface_get_by_instance_and_network(context,
                instance_uuid, network_id)
        if db_vif:
            return cls._from_db_object(context, cls(), db_vif)

    @base.remotable
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        updates = self.obj_get_changes()
        db_vif = db.virtual_interface_create(self._context, updates)
        self._from_db_object(self._context, self, db_vif)

    @base.remotable
    def save(self):
        updates = self.obj_get_changes()
        if 'address' in updates:
            raise exception.ObjectActionError(action='save',
                                              reason='address is not mutable')
        db_vif = db.virtual_interface_update(self._context, self.address,
                                             updates)
        return self._from_db_object(self._context, self, db_vif)

    @base.remotable_classmethod
    def delete_by_instance_uuid(cls, context, instance_uuid):
        db.virtual_interface_delete_by_instance(context, instance_uuid)

    @base.remotable
    def destroy(self):
        db.virtual_interface_delete(self._context, self.id)


@base.NovaObjectRegistry.register
class VirtualInterfaceList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'
    fields = {
        'objects': fields.ListOfObjectsField('VirtualInterface'),
    }

    @base.remotable_classmethod
    def get_all(cls, context):
        db_vifs = db.virtual_interface_get_all(context)
        return base.obj_make_list(context, cls(context),
                                  objects.VirtualInterface, db_vifs)

    @staticmethod
    @db.select_db_reader_mode
    def _db_virtual_interface_get_by_instance(context, instance_uuid,
                                              use_slave=False):
        return db.virtual_interface_get_by_instance(context, instance_uuid)

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid, use_slave=False):
        db_vifs = cls._db_virtual_interface_get_by_instance(
            context, instance_uuid, use_slave=use_slave)
        return base.obj_make_list(context, cls(context),
                                  objects.VirtualInterface, db_vifs)


@db_api.api_context_manager.writer
def fill_virtual_interface_list(context, max_count):
    """This fills missing VirtualInterface Objects in Nova DB"""
    count_hit = 0
    count_all = 0

    def _regenerate_vif_list_base_on_cache(context,
                                           instance,
                                           old_vif_list,
                                           nw_info):
        # Set old VirtualInterfaces as deleted.
        for vif in old_vif_list:
            vif.destroy()

        # Generate list based on current cache:
        for vif in nw_info:
            vif_obj = objects.VirtualInterface(context)
            vif_obj.uuid = vif['id']
            vif_obj.address = "%s/%s" % (vif['address'], vif['id'])
            vif_obj.instance_uuid = instance['uuid']
            # Find tag from previous VirtualInterface object if exist.
            old_vif = [x for x in old_vif_list if x.uuid == vif['id']]
            vif_obj.tag = old_vif[0].tag if len(old_vif) > 0 else None
            vif_obj.create()

    cells = objects.CellMappingList.get_all(context)
    for cell in cells:
        if count_all == max_count:
            # We reached the limit of checked instances per
            # this function run.
            # Stop, do not go to other cell.
            break

        with nova_context.target_cell(context, cell) as cctxt:
            marker = _get_marker_for_migrate_instances(cctxt)
            filters = {'deleted': False}

            # Adjust the limit of migrated instances.
            # If user wants to process a total of 100 instances
            # and we did a 75 in cell1, then we only need to
            # verify 25 more in cell2, no more.
            adjusted_limit = max_count - count_all

            instances = objects.InstanceList.get_by_filters(
                cctxt,
                filters=filters,
                sort_key='created_at',
                sort_dir='asc',
                marker=marker,
                limit=adjusted_limit)

            for instance in instances:
                # We don't want to fill vif for FAKE instance.
                if instance.uuid == FAKE_UUID:
                    continue

                try:
                    info_cache = objects.InstanceInfoCache.\
                        get_by_instance_uuid(cctxt, instance.get('uuid'))
                    if not info_cache.network_info:
                        LOG.info('InstanceInfoCache object has not set '
                                 'NetworkInfo field. '
                                 'Skipping build of VirtualInterfaceList.')
                        continue
                except exception.InstanceInfoCacheNotFound:
                    LOG.info('Instance has no InstanceInfoCache object. '
                             'Skipping build of VirtualInterfaceList for it.')
                    continue

                # It by design filters out deleted vifs.
                vif_list = VirtualInterfaceList.\
                    get_by_instance_uuid(cctxt, instance.get('uuid'))

                nw_info = info_cache.network_info
                # This should be list with proper order of vifs,
                # but we're not sure about that.
                cached_vif_ids = [vif['id'] for vif in nw_info]
                # This is ordered list of vifs taken from db.
                db_vif_ids = [vif.uuid for vif in vif_list]

                count_all += 1
                if cached_vif_ids == db_vif_ids:
                    # The list of vifs and its order in cache and in
                    # virtual_interfaces is the same. So we could end here.
                    continue
                elif len(db_vif_ids) < len(cached_vif_ids):
                    # Seems to be an instance from release older than
                    # Newton and we don't have full VirtualInterfaceList for
                    # it. Rewrite whole VirtualInterfaceList using interface
                    # order from InstanceInfoCache.
                    count_hit += 1
                    LOG.info('Got an instance %s with less VIFs defined in DB '
                             'than in cache. Could be Pre-Newton instance. '
                             'Building new VirtualInterfaceList for it.',
                             instance.uuid)
                    _regenerate_vif_list_base_on_cache(cctxt,
                                                       instance,
                                                       vif_list,
                                                       nw_info)
                elif len(db_vif_ids) > len(cached_vif_ids):
                    # Seems vif list is inconsistent with cache.
                    # it could be a broken cache or interface
                    # during attach. Do nothing.
                    LOG.info('Got an unexpected number of VIF records in the '
                             'database compared to what was stored in the '
                             'instance_info_caches table for instance %s. '
                             'Perhaps it is an instance during interface '
                             'attach. Do nothing.', instance.uuid)
                    continue
                else:
                    # The order is different between lists.
                    # We need a source of truth, so rebuild order
                    # from cache.
                    count_hit += 1
                    LOG.info('Got an instance %s with different order of '
                             'VIFs between DB and cache. '
                             'We need a source of truth, so rebuild order '
                             'from cache.', instance.uuid)
                    _regenerate_vif_list_base_on_cache(cctxt,
                                                       instance,
                                                       vif_list,
                                                       nw_info)

            # Set marker to point last checked instance.
            if instances:
                marker = instances[-1].uuid
                _set_or_delete_marker_for_migrate_instances(cctxt, marker)

    return count_all, count_hit


# NOTE(mjozefcz): This is similiar to marker mechanism made for
# RequestSpecs object creation.
# Since we have a lot of instances to be check this
# will add a FAKE row that points to last instance
# we checked.
# Please notice that because of virtual_interfaces_instance_uuid_fkey
# we need to have FAKE_UUID instance object, even deleted one.
@db_api.pick_context_manager_writer
def _set_or_delete_marker_for_migrate_instances(context, marker=None):
    context.session.query(models.VirtualInterface).filter_by(
        instance_uuid=FAKE_UUID).delete()

    # Create FAKE_UUID instance objects, only for marker, if doesn't exist.
    # It is needed due constraint: virtual_interfaces_instance_uuid_fkey
    instance = context.session.query(models.Instance).filter_by(
        uuid=FAKE_UUID).first()
    if not instance:
        instance = objects.Instance(context)
        instance.uuid = FAKE_UUID
        instance.project_id = FAKE_UUID
        instance.user_id = FAKE_UUID
        instance.create()
        # Thats fake instance, lets destroy it.
        # We need only its row to solve constraint issue.
        instance.destroy()

    if marker is not None:
        # ... but there can be a new marker to set
        db_mapping = objects.VirtualInterface(context)
        db_mapping.instance_uuid = FAKE_UUID
        db_mapping.uuid = FAKE_UUID
        db_mapping.tag = marker
        db_mapping.address = 'ff:ff:ff:ff:ff:ff/%s' % FAKE_UUID
        db_mapping.create()


@db_api.pick_context_manager_reader
def _get_marker_for_migrate_instances(context):
    vif = (context.session.query(models.VirtualInterface).filter_by(
           instance_uuid=FAKE_UUID)).first()
    marker = vif['tag'] if vif else None
    return marker
