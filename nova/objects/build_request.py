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
    VERSION = '1.0'

    fields = {
        'id': fields.IntegerField(),
        'instance_uuid': fields.UUIDField(),
        'project_id': fields.StringField(),
        'instance': fields.ObjectField('Instance'),
        # NOTE(alaski): Normally these would come from the NovaPersistentObject
        # mixin but they're being set explicitly because we only need
        # created_at/updated_at. There is no soft delete for this object.
        'created_at': fields.DateTimeField(nullable=True),
        'updated_at': fields.DateTimeField(nullable=True),
    }

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

    @staticmethod
    def _from_db_object(context, req, db_req):
        # Set this up front so that it can be pulled for error messages or
        # logging at any point.
        req.instance_uuid = db_req['instance_uuid']

        for key in req.fields:
            if isinstance(req.fields[key], fields.ObjectField):
                try:
                    getattr(req, '_load_%s' % key)(db_req[key])
                except AttributeError:
                    LOG.exception(_LE('No load handler for %s'), key)
            else:
                setattr(req, key, db_req[key])
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
    def _destroy_in_db(context, id):
        context.session.query(api_models.BuildRequest).filter_by(
                id=id).delete()

    @base.remotable
    def destroy(self):
        self._destroy_in_db(self._context, self.id)
