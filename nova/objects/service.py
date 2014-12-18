#    Copyright 2013 IBM Corp.
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

from nova import availability_zones
from nova import db
from nova import exception
from nova import objects
from nova.objects import base
from nova.objects import fields
from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)


# TODO(berrange): Remove NovaObjectDictCompat
class Service(base.NovaPersistentObject, base.NovaObject,
              base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: Added compute_node nested object
    # Version 1.2: String attributes updated to support unicode
    # Version 1.3: ComputeNode version 1.5
    # Version 1.4: Added use_slave to get_by_compute_host
    # Version 1.5: ComputeNode version 1.6
    # Version 1.6: ComputeNode version 1.7
    # Version 1.7: ComputeNode version 1.8
    # Version 1.8: ComputeNode version 1.9
    VERSION = '1.8'

    fields = {
        'id': fields.IntegerField(read_only=True),
        'host': fields.StringField(nullable=True),
        'binary': fields.StringField(nullable=True),
        'topic': fields.StringField(nullable=True),
        'report_count': fields.IntegerField(),
        'disabled': fields.BooleanField(),
        'disabled_reason': fields.StringField(nullable=True),
        'availability_zone': fields.StringField(nullable=True),
        'compute_node': fields.ObjectField('ComputeNode'),
        }

    obj_relationships = {
        'compute_node': [('1.1', '1.4'), ('1.3', '1.5'), ('1.5', '1.6'),
                         ('1.7', '1.8'), ('1.8', '1.9')],
    }

    @staticmethod
    def _do_compute_node(context, service, db_service):
        try:
            # NOTE(danms): The service.compute_node relationship returns
            # a list, which should only have one item in it. If it's empty
            # or otherwise malformed, ignore it.
            db_compute = db_service['compute_node'][0]
        except Exception:
            return
        service.compute_node = objects.ComputeNode._from_db_object(
            context, objects.ComputeNode(), db_compute)

    @staticmethod
    def _from_db_object(context, service, db_service):
        allow_missing = ('availability_zone',)
        for key in service.fields:
            if key in allow_missing and key not in db_service:
                continue
            if key == 'compute_node':
                service._do_compute_node(context, service, db_service)
            else:
                service[key] = db_service[key]
        service._context = context
        service.obj_reset_changes()
        return service

    def obj_load_attr(self, attrname):
        if not self._context:
            raise exception.OrphanedObjectError(method='obj_load_attr',
                                                objtype=self.obj_name())
        LOG.debug("Lazy-loading `%(attr)s' on %(name)s id %(id)s",
                  {'attr': attrname,
                   'name': self.obj_name(),
                   'id': self.id,
                   })
        if attrname != 'compute_node':
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason='attribute %s not lazy-loadable' % attrname)
        self.compute_node = objects.ComputeNode.get_by_service_id(
            self._context, self.id)

    @base.remotable_classmethod
    def get_by_id(cls, context, service_id):
        db_service = db.service_get(context, service_id)
        return cls._from_db_object(context, cls(), db_service)

    @base.remotable_classmethod
    def get_by_host_and_topic(cls, context, host, topic):
        db_service = db.service_get_by_host_and_topic(context, host, topic)
        return cls._from_db_object(context, cls(), db_service)

    @base.remotable_classmethod
    def get_by_compute_host(cls, context, host, use_slave=False):
        db_service = db.service_get_by_compute_host(context, host)
        return cls._from_db_object(context, cls(), db_service)

    @base.remotable_classmethod
    def get_by_args(cls, context, host, binary):
        db_service = db.service_get_by_args(context, host, binary)
        return cls._from_db_object(context, cls(), db_service)

    @base.remotable
    def create(self, context):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        updates = self.obj_get_changes()
        db_service = db.service_create(context, updates)
        self._from_db_object(context, self, db_service)

    @base.remotable
    def save(self, context):
        updates = self.obj_get_changes()
        updates.pop('id', None)
        db_service = db.service_update(context, self.id, updates)
        self._from_db_object(context, self, db_service)

    @base.remotable
    def destroy(self, context):
        db.service_destroy(context, self.id)


class ServiceList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    #              Service <= version 1.2
    # Version 1.1  Service version 1.3
    # Version 1.2: Service version 1.4
    # Version 1.3: Service version 1.5
    # Version 1.4: Service version 1.6
    # Version 1.5: Service version 1.7
    # Version 1.6: Service version 1.8
    VERSION = '1.6'

    fields = {
        'objects': fields.ListOfObjectsField('Service'),
        }
    child_versions = {
        '1.0': '1.2',
        # NOTE(danms): Service was at 1.2 before we added this
        '1.1': '1.3',
        '1.2': '1.4',
        '1.3': '1.5',
        '1.4': '1.6',
        '1.5': '1.7',
        '1.6': '1.8',
        }

    @base.remotable_classmethod
    def get_by_topic(cls, context, topic):
        db_services = db.service_get_all_by_topic(context, topic)
        return base.obj_make_list(context, cls(context), objects.Service,
                                  db_services)

    @base.remotable_classmethod
    def get_by_host(cls, context, host):
        db_services = db.service_get_all_by_host(context, host)
        return base.obj_make_list(context, cls(context), objects.Service,
                                  db_services)

    @base.remotable_classmethod
    def get_all(cls, context, disabled=None, set_zones=False):
        db_services = db.service_get_all(context, disabled=disabled)
        if set_zones:
            db_services = availability_zones.set_availability_zones(
                context, db_services)
        return base.obj_make_list(context, cls(context), objects.Service,
                                  db_services)
