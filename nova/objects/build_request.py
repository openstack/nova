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

from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import versionutils
from oslo_versionedobjects import exception as ovoo_exc
import six

from nova.db.sqlalchemy import api as db
from nova.db.sqlalchemy import api_models
from nova import exception
from nova.i18n import _LE
from nova import objects
from nova.objects import base
from nova.objects import fields

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


@base.NovaObjectRegistry.register
class BuildRequest(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Added block_device_mappings
    VERSION = '1.1'

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
    }

    def obj_make_compatible(self, primitive, target_version):
        super(BuildRequest, self).obj_make_compatible(primitive,
                                                      target_version)
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 1) and 'block_device_mappings' in primitive:
            del primitive['block_device_mappings']

    def _load_instance(self, db_instance):
        # NOTE(alaski): Be very careful with instance loading because it
        # changes more than most objects.
        try:
            self.instance = objects.Instance.obj_from_primitive(
                    jsonutils.loads(db_instance))
        except TypeError:
            LOG.debug('Failed to load instance from BuildRequest with uuid '
                      '%s because it is None' % (self.instance_uuid))
            raise exception.BuildRequestNotFound(uuid=self.instance_uuid)
        except ovoo_exc.IncompatibleObjectVersion as exc:
            # This should only happen if proper service upgrade strategies are
            # not followed. Log the exception and raise BuildRequestNotFound.
            # If the instance can't be loaded this object is useless and may
            # as well not exist.
            LOG.debug('Could not deserialize instance store in BuildRequest '
                      'with uuid %(instance_uuid)s. Found version %(version)s '
                      'which is not supported here.',
                      dict(instance_uuid=self.instance_uuid,
                          version=exc.objver))
            LOG.exception(_LE('Could not deserialize instance in '
                              'BuildRequest'))
            raise exception.BuildRequestNotFound(uuid=self.instance_uuid)
        # NOTE(alaski): Set some fields on instance that are needed by the api,
        # not lazy-loadable, and don't change.
        self.instance.deleted = 0
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
        self.instance.tags = objects.TagList([])

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
                    LOG.exception(_LE('No load handler for %s'), key)
            else:
                setattr(req, key, db_req[key])
        # Load instance last because other fields on req may be referenced
        req._load_instance(db_req['instance'])
        req.obj_reset_changes()
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
        for key, value in six.iteritems(updates):
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
