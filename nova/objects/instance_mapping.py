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

import collections

from oslo_log import log as logging
from oslo_utils import versionutils
import six
from sqlalchemy.orm import exc as orm_exc
from sqlalchemy.orm import joinedload
from sqlalchemy.sql import false
from sqlalchemy.sql import func
from sqlalchemy.sql import or_

from nova import context as nova_context
from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import api_models
from nova import exception
from nova.i18n import _
from nova import objects
from nova.objects import base
from nova.objects import cell_mapping
from nova.objects import fields
from nova.objects import virtual_interface


LOG = logging.getLogger(__name__)


@base.NovaObjectRegistry.register
class InstanceMapping(base.NovaTimestampObject, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Add queued_for_delete
    # Version 1.2: Add user_id
    VERSION = '1.2'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'instance_uuid': fields.UUIDField(),
        'cell_mapping': fields.ObjectField('CellMapping', nullable=True),
        'project_id': fields.StringField(),
        'user_id': fields.StringField(),
        'queued_for_delete': fields.BooleanField(default=False),
        }

    def obj_make_compatible(self, primitive, target_version):
        super(InstanceMapping, self).obj_make_compatible(primitive,
                                                         target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 2) and 'user_id' in primitive:
            del primitive['user_id']
        if target_version < (1, 1):
            if 'queued_for_delete' in primitive:
                del primitive['queued_for_delete']

    def obj_load_attr(self, attrname):
        if attrname == 'user_id':
            LOG.error('The unset user_id attribute of an unmigrated instance '
                      'mapping should not be accessed.')
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason=_('attribute user_id is not lazy-loadable'))
        super(InstanceMapping, self).obj_load_attr(attrname)

    def _update_with_cell_id(self, updates):
        cell_mapping_obj = updates.pop("cell_mapping", None)
        if cell_mapping_obj:
            updates["cell_id"] = cell_mapping_obj.id
        return updates

    @staticmethod
    def _from_db_object(context, instance_mapping, db_instance_mapping):
        for key in instance_mapping.fields:
            db_value = db_instance_mapping.get(key)
            if key == 'cell_mapping':
                # cell_mapping can be None indicating that the instance has
                # not been scheduled yet.
                if db_value:
                    db_value = cell_mapping.CellMapping._from_db_object(
                        context, cell_mapping.CellMapping(), db_value)
            if key == 'user_id' and db_value is None:
                # NOTE(melwitt): If user_id is NULL, we can't set the field
                # because it's non-nullable. We don't plan for any code to read
                # the user_id field at this time, so skip setting it.
                continue
            setattr(instance_mapping, key, db_value)
        instance_mapping.obj_reset_changes()
        instance_mapping._context = context
        return instance_mapping

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_by_instance_uuid_from_db(context, instance_uuid):
        db_mapping = (context.session.query(api_models.InstanceMapping)
                        .options(joinedload('cell_mapping'))
                        .filter(
                            api_models.InstanceMapping.instance_uuid ==
                            instance_uuid)).first()
        if not db_mapping:
            raise exception.InstanceMappingNotFound(uuid=instance_uuid)

        return db_mapping

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        db_mapping = cls._get_by_instance_uuid_from_db(context, instance_uuid)
        return cls._from_db_object(context, cls(), db_mapping)

    @staticmethod
    @db_api.api_context_manager.writer
    def _create_in_db(context, updates):
        db_mapping = api_models.InstanceMapping()
        db_mapping.update(updates)
        db_mapping.save(context.session)
        # NOTE: This is done because a later access will trigger a lazy load
        # outside of the db session so it will fail. We don't lazy load
        # cell_mapping on the object later because we never need an
        # InstanceMapping without the CellMapping.
        db_mapping.cell_mapping
        return db_mapping

    @base.remotable
    def create(self):
        changes = self.obj_get_changes()
        changes = self._update_with_cell_id(changes)
        if 'queued_for_delete' not in changes:
            # NOTE(danms): If we are creating a mapping, it should be
            # not queued_for_delete (unless we are being asked to
            # create one in deleted state for some reason).
            changes['queued_for_delete'] = False
        db_mapping = self._create_in_db(self._context, changes)
        self._from_db_object(self._context, self, db_mapping)

    @staticmethod
    @db_api.api_context_manager.writer
    def _save_in_db(context, instance_uuid, updates):
        db_mapping = context.session.query(
                api_models.InstanceMapping).filter_by(
                        instance_uuid=instance_uuid).first()
        if not db_mapping:
            raise exception.InstanceMappingNotFound(uuid=instance_uuid)

        db_mapping.update(updates)
        # NOTE: This is done because a later access will trigger a lazy load
        # outside of the db session so it will fail. We don't lazy load
        # cell_mapping on the object later because we never need an
        # InstanceMapping without the CellMapping.
        db_mapping.cell_mapping
        context.session.add(db_mapping)
        return db_mapping

    @base.remotable
    def save(self):
        changes = self.obj_get_changes()
        changes = self._update_with_cell_id(changes)
        try:
            db_mapping = self._save_in_db(self._context, self.instance_uuid,
                    changes)
        except orm_exc.StaleDataError:
            # NOTE(melwitt): If the instance mapping has been deleted out from
            # under us by conductor (delete requested while booting), we will
            # encounter a StaleDataError after we retrieved the row and try to
            # update it after it's been deleted. We can treat this like an
            # instance mapping not found and allow the caller to handle it.
            raise exception.InstanceMappingNotFound(uuid=self.instance_uuid)
        self._from_db_object(self._context, self, db_mapping)
        self.obj_reset_changes()

    @staticmethod
    @db_api.api_context_manager.writer
    def _destroy_in_db(context, instance_uuid):
        result = context.session.query(api_models.InstanceMapping).filter_by(
                instance_uuid=instance_uuid).delete()
        if not result:
            raise exception.InstanceMappingNotFound(uuid=instance_uuid)

    @base.remotable
    def destroy(self):
        self._destroy_in_db(self._context, self.instance_uuid)


@db_api.api_context_manager.writer
def populate_queued_for_delete(context, max_count):
    cells = objects.CellMappingList.get_all(context)
    processed = 0
    for cell in cells:
        ims = (
            # Get a direct list of instance mappings for this cell which
            # have not yet received a defined value decision for
            # queued_for_delete
            context.session.query(api_models.InstanceMapping)
            .filter(
                api_models.InstanceMapping.queued_for_delete == None)  # noqa
            .filter(api_models.InstanceMapping.cell_id == cell.id)
            .limit(max_count).all())
        ims_by_inst = {im.instance_uuid: im for im in ims}
        if not ims_by_inst:
            # If there is nothing from this cell to migrate, move on.
            continue
        with nova_context.target_cell(context, cell) as cctxt:
            filters = {'uuid': list(ims_by_inst.keys()),
                       'deleted': True,
                       'soft_deleted': True}
            instances = objects.InstanceList.get_by_filters(
                cctxt, filters, expected_attrs=[])
        # Walk through every deleted instance that has a mapping needing
        # to be updated and update it
        for instance in instances:
            im = ims_by_inst.pop(instance.uuid)
            im.queued_for_delete = True
            context.session.add(im)
            processed += 1
        # Any instances we did not just hit must be not-deleted, so
        # update the remaining mappings
        for non_deleted_im in ims_by_inst.values():
            non_deleted_im.queued_for_delete = False
            context.session.add(non_deleted_im)
            processed += 1
        max_count -= len(ims)
        if max_count <= 0:
            break

    return processed, processed


@db_api.api_context_manager.writer
def populate_user_id(context, max_count):
    cells = objects.CellMappingList.get_all(context)
    cms_by_id = {cell.id: cell for cell in cells}
    done = 0
    unmigratable_ims = False
    ims = (
        # Get a list of instance mappings which do not have user_id populated.
        # We need to include records with queued_for_delete=True because they
        # include SOFT_DELETED instances, which could be restored at any time
        # in the future. If we don't migrate SOFT_DELETED instances now, we
        # wouldn't be able to retire this migration code later. Also filter
        # out the marker instance created by the virtual interface migration.
        context.session.query(api_models.InstanceMapping)
        .filter_by(user_id=None)
        .filter(api_models.InstanceMapping.project_id !=
                virtual_interface.FAKE_UUID)
        .limit(max_count).all())
    found = len(ims)
    ims_by_inst_uuid = {}
    inst_uuids_by_cell_id = collections.defaultdict(set)
    for im in ims:
        ims_by_inst_uuid[im.instance_uuid] = im
        inst_uuids_by_cell_id[im.cell_id].add(im.instance_uuid)
    for cell_id, inst_uuids in inst_uuids_by_cell_id.items():
        # We cannot migrate instance mappings that don't have a cell yet.
        if cell_id is None:
            unmigratable_ims = True
            continue
        with nova_context.target_cell(context, cms_by_id[cell_id]) as cctxt:
            # We need to migrate SOFT_DELETED instances because they could be
            # restored at any time in the future, preventing us from being able
            # to remove any other interim online data migration code we have,
            # if we don't migrate them here.
            # NOTE: it's not possible to query only for SOFT_DELETED instances.
            # We must query for both deleted and SOFT_DELETED instances.
            filters = {'uuid': inst_uuids}
            try:
                instances = objects.InstanceList.get_by_filters(
                    cctxt, filters, expected_attrs=[])
            except Exception as exp:
                LOG.warning('Encountered exception: "%s" while querying '
                            'instances from cell: %s. Continuing to the next '
                            'cell.', six.text_type(exp),
                            cms_by_id[cell_id].identity)
                continue
        # Walk through every instance that has a mapping needing to be updated
        # and update it.
        for instance in instances:
            im = ims_by_inst_uuid.pop(instance.uuid)
            im.user_id = instance.user_id
            context.session.add(im)
            done += 1
        if ims_by_inst_uuid:
            unmigratable_ims = True
        if done >= max_count:
            break

    if unmigratable_ims:
        LOG.warning('Some instance mappings were not migratable. This may '
                    'be transient due to in-flight instance builds, or could '
                    'be due to stale data that will be cleaned up after '
                    'running "nova-manage db archive_deleted_rows --purge".')

    return found, done


@base.NovaObjectRegistry.register
class InstanceMappingList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Added get_by_cell_id method.
    # Version 1.2: Added get_by_instance_uuids method
    # Version 1.3: Added get_counts()
    VERSION = '1.3'

    fields = {
        'objects': fields.ListOfObjectsField('InstanceMapping'),
        }

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_by_project_id_from_db(context, project_id):
        return (context.session.query(api_models.InstanceMapping)
                .options(joinedload('cell_mapping'))
                .filter(
                    api_models.InstanceMapping.project_id == project_id)).all()

    @base.remotable_classmethod
    def get_by_project_id(cls, context, project_id):
        db_mappings = cls._get_by_project_id_from_db(context, project_id)

        return base.obj_make_list(context, cls(), objects.InstanceMapping,
                db_mappings)

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_by_cell_id_from_db(context, cell_id):
        return (context.session.query(api_models.InstanceMapping)
                .options(joinedload('cell_mapping'))
                .filter(api_models.InstanceMapping.cell_id == cell_id)).all()

    @base.remotable_classmethod
    def get_by_cell_id(cls, context, cell_id):
        db_mappings = cls._get_by_cell_id_from_db(context, cell_id)
        return base.obj_make_list(context, cls(), objects.InstanceMapping,
                db_mappings)

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_by_instance_uuids_from_db(context, uuids):
        return (context.session.query(api_models.InstanceMapping)
                .options(joinedload('cell_mapping'))
                .filter(api_models.InstanceMapping.instance_uuid.in_(uuids))
                .all())

    @base.remotable_classmethod
    def get_by_instance_uuids(cls, context, uuids):
        db_mappings = cls._get_by_instance_uuids_from_db(context, uuids)
        return base.obj_make_list(context, cls(), objects.InstanceMapping,
                db_mappings)

    @staticmethod
    @db_api.api_context_manager.writer
    def _destroy_bulk_in_db(context, instance_uuids):
        return context.session.query(api_models.InstanceMapping).filter(
                api_models.InstanceMapping.instance_uuid.in_(instance_uuids)).\
                delete(synchronize_session=False)

    @classmethod
    def destroy_bulk(cls, context, instance_uuids):
        return cls._destroy_bulk_in_db(context, instance_uuids)

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_not_deleted_by_cell_and_project_from_db(context, cell_uuid,
                                                     project_id, limit):
        query = context.session.query(api_models.InstanceMapping)
        if project_id is not None:
            # Note that the project_id can be None in case
            # instances are being listed for the all-tenants case.
            query = query.filter_by(project_id=project_id)
        # Both the values NULL (for cases when the online data migration for
        # queued_for_delete was not run) and False (cases when the online
        # data migration for queued_for_delete was run) are assumed to mean
        # that the instance is not queued for deletion.
        query = (query.filter(or_(
            api_models.InstanceMapping.queued_for_delete == false(),
            api_models.InstanceMapping.queued_for_delete.is_(None)))
            .join('cell_mapping')
            .options(joinedload('cell_mapping'))
            .filter(api_models.CellMapping.uuid == cell_uuid))
        if limit is not None:
            query = query.limit(limit)
        return query.all()

    @classmethod
    def get_not_deleted_by_cell_and_project(cls, context, cell_uuid,
                                            project_id, limit=None):
        """Return a limit restricted list of InstanceMapping objects which are
        mapped to the specified cell_uuid, belong to the specified
        project_id and are not queued for deletion (note that unlike the other
        InstanceMappingList query methods which return all mappings
        irrespective of whether they are queued for deletion this method
        explicitly queries only for those mappings that are *not* queued for
        deletion as is evident from the naming of the method).
        """
        db_mappings = cls._get_not_deleted_by_cell_and_project_from_db(
            context, cell_uuid, project_id, limit)
        return base.obj_make_list(context, cls(), objects.InstanceMapping,
                db_mappings)

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_counts_in_db(context, project_id, user_id=None):
        project_query = context.session.query(
            func.count(api_models.InstanceMapping.id)).\
            filter_by(queued_for_delete=False).\
            filter_by(project_id=project_id)
        project_result = project_query.scalar()
        counts = {'project': {'instances': project_result}}
        if user_id:
            user_result = project_query.filter_by(user_id=user_id).scalar()
            counts['user'] = {'instances': user_result}
        return counts

    @base.remotable_classmethod
    def get_counts(cls, context, project_id, user_id=None):
        """Get the counts of InstanceMapping objects in the database.

        The count is used to represent the count of instances for the purpose
        of counting quota usage. Instances that are queued_for_deleted=True are
        not included in the count (deleted and SOFT_DELETED instances).
        Instances that are queued_for_deleted=None are not included in the
        count because we are not certain about whether or not they are deleted.

        :param context: The request context for database access
        :param project_id: The project_id to count across
        :param user_id: The user_id to count across
        :returns: A dict containing the project-scoped counts and user-scoped
                  counts if user_id is specified. For example:

                    {'project': {'instances': <count across project>},
                     'user': {'instances': <count across user>}}
        """
        return cls._get_counts_in_db(context, project_id, user_id=user_id)

    @staticmethod
    @db_api.api_context_manager.reader
    def _get_count_by_uuids_and_user_in_db(context, uuids, user_id):
        query = (context.session.query(
            func.count(api_models.InstanceMapping.id))
            .filter(api_models.InstanceMapping.instance_uuid.in_(uuids))
            .filter_by(queued_for_delete=False)
            .filter_by(user_id=user_id))
        return query.scalar()

    @classmethod
    def get_count_by_uuids_and_user(cls, context, uuids, user_id):
        """Get the count of InstanceMapping objects by UUIDs and user_id.

        The count is used to represent the count of server group members
        belonging to a particular user, for the purpose of counting quota
        usage. Instances that are queued_for_deleted=True are not included in
        the count (deleted and SOFT_DELETED instances).

        :param uuids: List of instance UUIDs on which to filter
        :param user_id: The user_id on which to filter
        :returns: An integer for the count
        """
        return cls._get_count_by_uuids_and_user_in_db(context, uuids, user_id)
