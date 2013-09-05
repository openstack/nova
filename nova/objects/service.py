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
from nova.objects import base
from nova.objects import compute_node
from nova.objects import utils


class Service(base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Added compute_node nested object
    VERSION = '1.1'

    fields = {
        'id': int,
        'host': utils.str_or_none,
        'binary': utils.str_or_none,
        'topic': utils.str_or_none,
        'report_count': int,
        'disabled': bool,
        'disabled_reason': utils.str_or_none,
        'availability_zone': utils.str_or_none,
        'compute_node': utils.nested_object_or_none(
            compute_node.ComputeNode),
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
        service.compute_node = compute_node.ComputeNode._from_db_object(
            context, compute_node.ComputeNode(), db_compute)

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
        if attrname != 'compute_node':
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason='attribute %s not lazy-loadable' % attrname)
        self.compute_node = compute_node.ComputeNode.get_by_service_id(
            self._context, self.id)

    _attr_compute_node_to_primitive = utils.obj_serializer('compute_node')

    def _attr_compute_node_from_primitive(self, val):
        return base.NovaObject.obj_from_primitive(val)

    @base.remotable_classmethod
    def get_by_id(cls, context, service_id):
        db_service = db.service_get(context, service_id)
        return cls._from_db_object(context, cls(), db_service)

    @base.remotable_classmethod
    def get_by_host_and_topic(cls, context, host, topic):
        db_service = db.service_get_by_host_and_topic(context, host, topic)
        return cls._from_db_object(context, cls(), db_service)

    @base.remotable_classmethod
    def get_by_compute_host(cls, context, host):
        db_service = db.service_get_by_compute_host(context, host)
        return cls._from_db_object(context, cls(), db_service)

    @base.remotable_classmethod
    def get_by_args(cls, context, host, binary):
        db_service = db.service_get_by_args(context, host, binary)
        return cls._from_db_object(context, cls(), db_service)

    @base.remotable
    def create(self, context):
        updates = {}
        for key in self.obj_what_changed():
            updates[key] = self[key]
        db_service = db.service_create(context, updates)
        self._from_db_object(context, self, db_service)

    @base.remotable
    def save(self, context):
        updates = {}
        for key in self.obj_what_changed():
            updates[key] = self[key]
        updates.pop('id', None)
        db_service = db.service_update(context, self.id, updates)
        self._from_db_object(context, self, db_service)

    @base.remotable
    def destroy(self, context):
        db.service_destroy(context, self.id)


class ServiceList(base.ObjectListBase, base.NovaObject):
    @base.remotable_classmethod
    def get_by_topic(cls, context, topic):
        db_services = db.service_get_all_by_topic(context, topic)
        return base.obj_make_list(context, ServiceList(), Service, db_services)

    @base.remotable_classmethod
    def get_by_host(cls, context, host):
        db_services = db.service_get_all_by_host(context, host)
        return base.obj_make_list(context, ServiceList(), Service, db_services)

    @base.remotable_classmethod
    def get_all(cls, context, disabled=None, set_zones=False):
        db_services = db.service_get_all(context, disabled=disabled)
        if set_zones:
            db_services = availability_zones.set_availability_zones(
                context, db_services)
        return base.obj_make_list(context, ServiceList(), Service, db_services)
