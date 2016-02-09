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

OBJECT_FIELDS = ['info_cache', 'security_groups']
JSON_FIELDS = ['instance_metadata']
IP_FIELDS = ['access_ip_v4', 'access_ip_v6']


@base.NovaObjectRegistry.register
class BuildRequest(base.NovaObject):
    # Version 1.0: Initial version
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(),
        'project_id': fields.StringField(),
        'user_id': fields.StringField(),
        'display_name': fields.StringField(nullable=True),
        'instance_metadata': fields.DictOfStringsField(nullable=True),
        'progress': fields.IntegerField(nullable=True),
        'vm_state': fields.StringField(nullable=True),
        'task_state': fields.StringField(nullable=True),
        'image_ref': fields.StringField(nullable=True),
        'access_ip_v4': fields.IPV4AddressField(nullable=True),
        'access_ip_v6': fields.IPV6AddressField(nullable=True),
        'info_cache': fields.ObjectField('InstanceInfoCache', nullable=True),
        'security_groups': fields.ObjectField('SecurityGroupList'),
        'config_drive': fields.BooleanField(default=False),
        'key_name': fields.StringField(nullable=True),
        'locked_by': fields.EnumField(['owner', 'admin'], nullable=True),
        'request_spec': fields.ObjectField('RequestSpec'),
        # NOTE(alaski): Normally these would come from the NovaPersistentObject
        # mixin but they're being set explicitly because we only need
        # created_at/updated_at. There is no soft delete for this object.
        # These fields should be carried over to the instance when it is
        # scheduled and created in a cell database.
        'created_at': fields.DateTimeField(nullable=True),
        'updated_at': fields.DateTimeField(nullable=True),
    }

    def _load_request_spec(self, db_spec):
        self.request_spec = objects.RequestSpec._from_db_object(self._context,
                objects.RequestSpec(), db_spec)

    def _load_info_cache(self, db_info_cache):
        self.info_cache = objects.InstanceInfoCache.obj_from_primitive(
                jsonutils.loads(db_info_cache))

    def _load_security_groups(self, db_sec_group):
        self.security_groups = objects.SecurityGroupList.obj_from_primitive(
                jsonutils.loads(db_sec_group))

    @staticmethod
    def _from_db_object(context, req, db_req):
        for key in req.fields:
            if isinstance(req.fields[key], fields.ObjectField):
                try:
                    getattr(req, '_load_%s' % key)(db_req[key])
                except AttributeError:
                    LOG.exception(_LE('No load handler for %s'), key)
            elif key in JSON_FIELDS and db_req[key] is not None:
                setattr(req, key, jsonutils.loads(db_req[key]))
            else:
                setattr(req, key, db_req[key])
        req.obj_reset_changes()
        req._context = context
        return req

    @staticmethod
    @db.api_context_manager.reader
    def _get_by_instance_uuid_from_db(context, instance_uuid):
        db_req = (context.session.query(api_models.BuildRequest)
                .join(api_models.RequestSpec)
                .with_entities(api_models.BuildRequest,
                               api_models.RequestSpec)
                .filter(
                    api_models.RequestSpec.instance_uuid == instance_uuid)
                ).first()
        if not db_req:
            raise exception.BuildRequestNotFound(uuid=instance_uuid)
        # db_req is a tuple (api_models.BuildRequest, api_models.RequestSpect)
        build_req = db_req[0]
        build_req['request_spec'] = db_req[1]
        return build_req

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
        # NOTE: This is done because a later access will trigger a lazy load
        # outside of the db session so it will fail. We don't lazy load
        # request_spec on the object later because we never need a BuildRequest
        # without the RequestSpec.
        db_req.request_spec
        return db_req

    def _get_update_primitives(self):
        updates = self.obj_get_changes()
        for key, value in six.iteritems(updates):
            if key in OBJECT_FIELDS and value is not None:
                updates[key] = jsonutils.dumps(value.obj_to_primitive())
            elif key in JSON_FIELDS and value is not None:
                updates[key] = jsonutils.dumps(value)
            elif key in IP_FIELDS and value is not None:
                # These are stored as a string in the db and must be converted
                updates[key] = str(value)
        req_spec_obj = updates.pop('request_spec', None)
        if req_spec_obj:
            updates['request_spec_id'] = req_spec_obj.id
        return updates

    @base.remotable
    def create(self):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')

        updates = self._get_update_primitives()
        db_req = self._create_in_db(self._context, updates)
        self._from_db_object(self._context, self, db_req)

    @staticmethod
    @db.api_context_manager.writer
    def _destroy_in_db(context, id):
        context.session.query(api_models.BuildRequest).filter_by(
                id=id).delete()

    @base.remotable
    def destroy(self):
        self._destroy_in_db(self._context, self.id)
