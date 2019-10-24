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

import functools
import re

from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import versionutils
from oslo_versionedobjects import exception as ovoo_exc
import six

from nova.db.sqlalchemy import api as db
from nova.db.sqlalchemy import api_models
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields

LOG = logging.getLogger(__name__)


@base.NovaObjectRegistry.register
class BuildRequest(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Added block_device_mappings
    # Version 1.2: Added save() method
    # Version 1.3: Added tags
    VERSION = '1.3'

    fields = {
        'id': fields.IntegerField(),
        'instance_uuid': fields.UUIDField(),
        'project_id': fields.StringField(),
        'instance': fields.ObjectField('Instance'),
        'block_device_mappings': fields.ObjectField('BlockDeviceMappingList'),
        # NOTE(alaski): Normally these would come from the NovaPersistentObject
        # mixin but they're being set explicitly because we only need
        # created_at/updated_at. There is no soft delete for this object.
        'created_at': fields.DateTimeField(nullable=True),
        'updated_at': fields.DateTimeField(nullable=True),
        'tags': fields.ObjectField('TagList'),
    }

    def obj_make_compatible(self, primitive, target_version):
        super(BuildRequest, self).obj_make_compatible(primitive,
                                                      target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 1) and 'block_device_mappings' in primitive:
            del primitive['block_device_mappings']
        elif target_version < (1, 3) and 'tags' in primitive:
            del primitive['tags']

    def _load_instance(self, db_instance):
        # NOTE(alaski): Be very careful with instance loading because it
        # changes more than most objects.
        try:
            self.instance = objects.Instance.obj_from_primitive(
                    jsonutils.loads(db_instance))
        except TypeError:
            LOG.debug('Failed to load instance from BuildRequest with uuid '
                      '%s because it is None', self.instance_uuid)
            raise exception.BuildRequestNotFound(uuid=self.instance_uuid)
        except ovoo_exc.IncompatibleObjectVersion:
            # This should only happen if proper service upgrade strategies are
            # not followed. Log the exception and raise BuildRequestNotFound.
            # If the instance can't be loaded this object is useless and may
            # as well not exist.
            LOG.debug('Could not deserialize instance store in BuildRequest '
                      'with uuid %(instance_uuid)s. Found version %(version)s '
                      'which is not supported here.',
                      dict(instance_uuid=self.instance_uuid,
                           version=jsonutils.loads(
                               db_instance)["nova_object.version"]))
            LOG.exception('Could not deserialize instance in BuildRequest')
            raise exception.BuildRequestNotFound(uuid=self.instance_uuid)
        # NOTE(sbauza): The instance primitive should already have the deleted
        # field being set, so when hydrating it back here, we should get the
        # right value but in case we don't have it, let's suppose that the
        # instance is not deleted, which is the default value for that field.
        # NOTE(mriedem): Same for the "hidden" field.
        self.instance.obj_set_defaults('deleted', 'hidden')
        # NOTE(alaski): Set some fields on instance that are needed by the api,
        # not lazy-loadable, and don't change.
        self.instance.disable_terminate = False
        self.instance.terminated_at = None
        self.instance.host = None
        self.instance.node = None
        self.instance.launched_at = None
        self.instance.launched_on = None
        self.instance.cell_name = None
        # The fields above are not set until the instance is in a cell at
        # which point this BuildRequest will be gone. locked_by could
        # potentially be set by an update so it should not be overwritten.
        if not self.instance.obj_attr_is_set('locked_by'):
            self.instance.locked_by = None
        # created_at/updated_at are not on the serialized instance because it
        # was never persisted.
        self.instance.created_at = self.created_at
        self.instance.updated_at = self.updated_at
        self.instance.tags = self.tags

    def _load_block_device_mappings(self, db_bdms):
        # 'db_bdms' is a serialized BlockDeviceMappingList object. If it's None
        # we're in a mixed version nova-api scenario and can't retrieve the
        # actual list. Set it to an empty list here which will cause a
        # temporary API inconsistency that will be resolved as soon as the
        # instance is scheduled and on a compute.
        if db_bdms is None:
            LOG.debug('Failed to load block_device_mappings from BuildRequest '
                      'for instance %s because it is None', self.instance_uuid)
            self.block_device_mappings = objects.BlockDeviceMappingList()
            return

        self.block_device_mappings = (
            objects.BlockDeviceMappingList.obj_from_primitive(
                jsonutils.loads(db_bdms)))

    def _load_tags(self, db_tags):
        # 'db_tags' is a serialized TagList object. If it's None
        # we're in a mixed version nova-api scenario and can't retrieve the
        # actual list. Set it to an empty list here which will cause a
        # temporary API inconsistency that will be resolved as soon as the
        # instance is scheduled and on a compute.
        if db_tags is None:
            LOG.debug('Failed to load tags from BuildRequest '
                      'for instance %s because it is None', self.instance_uuid)
            self.tags = objects.TagList()
            return

        self.tags = (
            objects.TagList.obj_from_primitive(
                jsonutils.loads(db_tags)))

    @staticmethod
    def _from_db_object(context, req, db_req):
        # Set this up front so that it can be pulled for error messages or
        # logging at any point.
        req.instance_uuid = db_req['instance_uuid']

        for key in req.fields:
            if key == 'instance':
                continue
            elif isinstance(req.fields[key], fields.ObjectField):
                try:
                    getattr(req, '_load_%s' % key)(db_req[key])
                except AttributeError:
                    LOG.exception('No load handler for %s', key)
            else:
                setattr(req, key, db_req[key])
        # Load instance last because other fields on req may be referenced
        req._load_instance(db_req['instance'])
        req.obj_reset_changes(recursive=True)
        req._context = context
        return req

    @staticmethod
    @db.api_context_manager.reader
    def _get_by_instance_uuid_from_db(context, instance_uuid):
        db_req = context.session.query(api_models.BuildRequest).filter_by(
                    instance_uuid=instance_uuid).first()
        if not db_req:
            raise exception.BuildRequestNotFound(uuid=instance_uuid)
        return db_req

    @base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        db_req = cls._get_by_instance_uuid_from_db(context, instance_uuid)
        return cls._from_db_object(context, cls(), db_req)

    @staticmethod
    @db.api_context_manager.writer
    def _create_in_db(context, updates):
        db_req = api_models.BuildRequest()
        db_req.update(updates)
        db_req.save(context.session)
        return db_req

    def _get_update_primitives(self):
        updates = self.obj_get_changes()
        for key, value in updates.items():
            if isinstance(self.fields[key], fields.ObjectField):
                updates[key] = jsonutils.dumps(value.obj_to_primitive())
        return updates

    @base.remotable
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        if not self.obj_attr_is_set('instance_uuid'):
            # We can't guarantee this is not null in the db so check here
            raise exception.ObjectActionError(action='create',
                    reason='instance_uuid must be set')

        updates = self._get_update_primitives()
        db_req = self._create_in_db(self._context, updates)
        self._from_db_object(self._context, self, db_req)

    @staticmethod
    @db.api_context_manager.writer
    def _destroy_in_db(context, instance_uuid):
        result = context.session.query(api_models.BuildRequest).filter_by(
                instance_uuid=instance_uuid).delete()
        if not result:
            raise exception.BuildRequestNotFound(uuid=instance_uuid)

    @base.remotable
    def destroy(self):
        self._destroy_in_db(self._context, self.instance_uuid)

    @db.api_context_manager.writer
    def _save_in_db(self, context, req_id, updates):
        db_req = context.session.query(
            api_models.BuildRequest).filter_by(id=req_id).first()
        if not db_req:
            raise exception.BuildRequestNotFound(uuid=self.instance_uuid)

        db_req.update(updates)
        context.session.add(db_req)
        return db_req

    @base.remotable
    def save(self):
        updates = self._get_update_primitives()
        db_req = self._save_in_db(self._context, self.id, updates)
        self._from_db_object(self._context, self, db_req)

    def get_new_instance(self, context):
        # NOTE(danms): This is a hack to make sure that the returned
        # instance has all dirty fields. There are probably better
        # ways to do this, but they kinda involve o.vo internals
        # so this is okay for the moment.
        instance = objects.Instance(context)
        for field in self.instance.obj_fields:
            # NOTE(danms): Don't copy the defaulted tags field
            # as instance.create() won't handle it properly.
            # TODO(zhengzhenyu): Handle this when the API supports creating
            # servers with tags.
            if field == 'tags':
                continue
            if self.instance.obj_attr_is_set(field):
                setattr(instance, field, getattr(self.instance, field))
        return instance


@base.NovaObjectRegistry.register
class BuildRequestList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('BuildRequest'),
    }

    @staticmethod
    @db.api_context_manager.reader
    def _get_all_from_db(context):
        query = context.session.query(api_models.BuildRequest)

        if not context.is_admin:
            query = query.filter_by(project_id=context.project_id)

        db_reqs = query.all()
        return db_reqs

    @base.remotable_classmethod
    def get_all(cls, context):
        db_build_reqs = cls._get_all_from_db(context)
        return base.obj_make_list(context, cls(context), objects.BuildRequest,
                                  db_build_reqs)

    @staticmethod
    def _pass_exact_filters(instance, filters):
        for filter_key, filter_val in filters.items():
            if filter_key in ('metadata', 'system_metadata'):
                if isinstance(filter_val, list):
                    for item in filter_val:
                        for k, v in item.items():
                            if (k not in instance.metadata or
                                    v != instance.metadata[k]):
                                return False
                else:
                    for k, v in filter_val.items():
                        if (k not in instance.metadata or
                                v != instance.metadata[k]):
                            return False
            elif filter_key in (
                    'tags', 'tags-any', 'not-tags', 'not-tags-any'):
                # Get the list of simple string tags first.
                tags = ([tag.tag for tag in instance.tags]
                        if instance.tags else [])
                if filter_key == 'tags':
                    for item in filter_val:
                        if item not in tags:
                            return False
                elif filter_key == 'tags-any':
                    found = []
                    for item in filter_val:
                        if item in tags:
                            found.append(item)
                    if not found:
                        return False
                elif filter_key == 'not-tags':
                    found = []
                    for item in filter_val:
                        if item in tags:
                            found.append(item)
                    if len(found) == len(filter_val):
                        return False
                elif filter_key == 'not-tags-any':
                    for item in filter_val:
                        if item in tags:
                            return False
            elif isinstance(filter_val, (list, tuple, set, frozenset)):
                if not filter_val:
                    # Special value to indicate that nothing will match.
                    return None
                if instance.get(filter_key, None) not in filter_val:
                    return False
            else:
                if instance.get(filter_key, None) != filter_val:
                    return False

        return True

    @staticmethod
    def _pass_regex_filters(instance, filters):
        for filter_name, filter_val in filters.items():
            try:
                instance_attr = getattr(instance, filter_name)
            except AttributeError:
                continue

            # Sometimes the REGEX filter value is not a string
            if not isinstance(filter_val, six.string_types):
                filter_val = str(filter_val)
            filter_re = re.compile(filter_val)
            if instance_attr and not filter_re.search(str(instance_attr)):
                return False

        return True

    @staticmethod
    def _sort_build_requests(build_req_list, sort_keys, sort_dirs):
        # build_req_list is a [] of build_reqs
        sort_keys.reverse()
        sort_dirs.reverse()

        def sort_attr(sort_key, build_req):
            if sort_key == 'id':
                # 'id' is not set on the instance yet. Use the BuildRequest
                # 'id' instead.
                return build_req.id
            return getattr(build_req.instance, sort_key)

        for sort_key, sort_dir in zip(sort_keys, sort_dirs):
            reverse = False if sort_dir.lower().startswith('asc') else True
            build_req_list.sort(key=functools.partial(sort_attr, sort_key),
                                reverse=reverse)
        return build_req_list

    @base.remotable_classmethod
    def get_by_filters(cls, context, filters, limit=None, marker=None,
                       sort_keys=None, sort_dirs=None):
        # Short-circuit on anything that will not yield results.
        # 'deleted' records can not be returned from here since build_requests
        # are not soft deleted.
        # 'cleaned' records won't exist as they would need to be deleted.
        if (limit == 0 or
                filters.get('deleted', False) or
                filters.get('cleaned', False)):
            # If we have a marker honor the MarkerNotFound semantics.
            if marker:
                raise exception.MarkerNotFound(marker=marker)
            return cls(context, objects=[])

        # Because the build_requests table stores an instance as a serialized
        # versioned object it is not feasible to do the filtering and sorting
        # in the database. Just get all potentially relevant records and
        # process them here. It should be noted that build requests are short
        # lived so there should not be a lot of results to deal with.
        build_requests = cls.get_all(context)

        # Fortunately some filters do not apply here.
        # 'changes-since' works off of the updated_at field which has not yet
        # been set at the point in the boot process where build_request still
        # exists. So it can be ignored.
        # 'deleted' and 'cleaned' are handled above.

        sort_keys, sort_dirs = db.process_sort_params(sort_keys, sort_dirs,
                                                      default_dir='desc')

        # For other filters that don't match this, we will do regexp matching
        # Taken from db/sqlalchemy/api.py
        exact_match_filter_names = ['project_id', 'user_id', 'image_ref',
                                    'vm_state', 'instance_type_id', 'uuid',
                                    'metadata', 'host', 'task_state',
                                    'system_metadata', 'tags', 'tags-any',
                                    'not-tags', 'not-tags-any']
        exact_filters = {}
        regex_filters = {}
        for key, value in filters.items():
            if key in exact_match_filter_names:
                exact_filters[key] = value
            else:
                regex_filters[key] = value

        # As much as possible this copies the logic from db/sqlalchemy/api.py
        # instance_get_all_by_filters_sort. The main difference is that method
        # builds a sql query and this filters in python.
        filtered_build_reqs = []

        for build_req in build_requests:
            instance = build_req.instance

            filter_result = cls._pass_exact_filters(instance, exact_filters)
            if filter_result is None:
                # The filter condition is such that nothing will match.
                # Bail early.
                return cls(context, objects=[])
            if filter_result is False:
                continue

            if not cls._pass_regex_filters(instance, regex_filters):
                continue

            filtered_build_reqs.append(build_req)

        if (((len(filtered_build_reqs) < 2) or (not sort_keys)) and
                not marker):
            # No need to sort
            return cls(context, objects=filtered_build_reqs)

        sorted_build_reqs = cls._sort_build_requests(filtered_build_reqs,
                                                     sort_keys, sort_dirs)

        marker_index = 0
        if marker:
            for i, build_req in enumerate(sorted_build_reqs):
                if build_req.instance.uuid == marker:
                    # The marker is the last seen item in the last page, so
                    # we increment the index to the next item immediately
                    # after the marker so the marker is not returned.
                    marker_index = i + 1
                    break
            else:
                raise exception.MarkerNotFound(marker=marker)
        len_build_reqs = len(sorted_build_reqs)
        limit_index = len_build_reqs
        if limit:
            limit_index = marker_index + limit
            if limit_index > len_build_reqs:
                limit_index = len_build_reqs

        return cls(context,
                   objects=sorted_build_reqs[marker_index:limit_index])
