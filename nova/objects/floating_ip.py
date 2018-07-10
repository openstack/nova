#    Copyright 2014 Red Hat, Inc.
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

from nova.db import api as db
from nova.db.sqlalchemy import api as db_api
from nova.db.sqlalchemy import models
from nova import exception
from nova import objects
from nova.objects import base as obj_base
from nova.objects import fields

FLOATING_IP_OPTIONAL_ATTRS = ['fixed_ip']


# TODO(berrange): Remove NovaObjectDictCompat
@obj_base.NovaObjectRegistry.register
class FloatingIP(obj_base.NovaPersistentObject, obj_base.NovaObject,
                 obj_base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: Added _get_addresses_by_instance_uuid()
    # Version 1.2: FixedIP <= version 1.2
    # Version 1.3: FixedIP <= version 1.3
    # Version 1.4: FixedIP <= version 1.4
    # Version 1.5: FixedIP <= version 1.5
    # Version 1.6: FixedIP <= version 1.6
    # Version 1.7: FixedIP <= version 1.11
    # Version 1.8: FixedIP <= version 1.12
    # Version 1.9: FixedIP <= version 1.13
    # Version 1.10: FixedIP <= version 1.14
    VERSION = '1.10'
    fields = {
        'id': fields.IntegerField(),
        'address': fields.IPAddressField(),
        'fixed_ip_id': fields.IntegerField(nullable=True),
        'project_id': fields.UUIDField(nullable=True),
        'host': fields.StringField(nullable=True),
        'auto_assigned': fields.BooleanField(),
        'pool': fields.StringField(nullable=True),
        'interface': fields.StringField(nullable=True),
        'fixed_ip': fields.ObjectField('FixedIP', nullable=True),
        }

    @staticmethod
    def _from_db_object(context, floatingip, db_floatingip,
                        expected_attrs=None):
        if expected_attrs is None:
            expected_attrs = []
        for field in floatingip.fields:
            if field not in FLOATING_IP_OPTIONAL_ATTRS:
                floatingip[field] = db_floatingip[field]
        if ('fixed_ip' in expected_attrs and
                db_floatingip['fixed_ip'] is not None):
            floatingip.fixed_ip = objects.FixedIP._from_db_object(
                context, objects.FixedIP(context), db_floatingip['fixed_ip'])
        floatingip._context = context
        floatingip.obj_reset_changes()
        return floatingip

    def obj_load_attr(self, attrname):
        if attrname not in FLOATING_IP_OPTIONAL_ATTRS:
            raise exception.ObjectActionError(
                action='obj_load_attr',
                reason='attribute %s is not lazy-loadable' % attrname)
        if not self._context:
            raise exception.OrphanedObjectError(method='obj_load_attr',
                                                objtype=self.obj_name())
        if self.fixed_ip_id is not None:
            self.fixed_ip = objects.FixedIP.get_by_id(
                self._context, self.fixed_ip_id, expected_attrs=['network'])
        else:
            self.fixed_ip = None

    @obj_base.remotable_classmethod
    def get_by_id(cls, context, id):
        db_floatingip = db.floating_ip_get(context, id)
        # XXX joins fixed.instance
        return cls._from_db_object(context, cls(context), db_floatingip,
                                   expected_attrs=['fixed_ip'])

    @obj_base.remotable_classmethod
    def get_by_address(cls, context, address):
        db_floatingip = db.floating_ip_get_by_address(context, str(address))
        return cls._from_db_object(context, cls(context), db_floatingip)

    @obj_base.remotable_classmethod
    def get_pool_names(cls, context):
        return [x['name'] for x in db.floating_ip_get_pools(context)]

    @obj_base.remotable_classmethod
    def allocate_address(cls, context, project_id, pool, auto_assigned=False):
        return db.floating_ip_allocate_address(context, project_id, pool,
                                               auto_assigned=auto_assigned)

    @obj_base.remotable_classmethod
    def associate(cls, context, floating_address, fixed_address, host):
        db_fixed = db.floating_ip_fixed_ip_associate(context,
                                                     str(floating_address),
                                                     str(fixed_address),
                                                     host)
        if db_fixed is None:
            return None

        floating = FloatingIP(
            context=context, address=floating_address, host=host,
            fixed_ip_id=db_fixed['id'],
            fixed_ip=objects.FixedIP._from_db_object(
                context, objects.FixedIP(context), db_fixed,
                expected_attrs=['network']))
        return floating

    @obj_base.remotable_classmethod
    def deallocate(cls, context, address):
        return db.floating_ip_deallocate(context, str(address))

    @obj_base.remotable_classmethod
    def destroy(cls, context, address):
        db.floating_ip_destroy(context, str(address))

    @obj_base.remotable_classmethod
    def disassociate(cls, context, address):
        db_fixed = db.floating_ip_disassociate(context, str(address))

        return cls(context=context, address=address,
                   fixed_ip_id=db_fixed['id'],
                   fixed_ip=objects.FixedIP._from_db_object(
                       context, objects.FixedIP(context), db_fixed,
                       expected_attrs=['network']))

    @obj_base.remotable_classmethod
    def _get_addresses_by_instance_uuid(cls, context, instance_uuid):
        return db.instance_floating_address_get_all(context, instance_uuid)

    @classmethod
    def get_addresses_by_instance(cls, context, instance):
        return cls._get_addresses_by_instance_uuid(context, instance['uuid'])

    @obj_base.remotable
    def save(self):
        updates = self.obj_get_changes()
        if 'address' in updates:
            raise exception.ObjectActionError(action='save',
                                              reason='address is not mutable')
        if 'fixed_ip_id' in updates:
            reason = 'fixed_ip_id is not mutable'
            raise exception.ObjectActionError(action='save', reason=reason)

        # NOTE(danms): Make sure we don't pass the calculated fixed_ip
        # relationship to the DB update method
        updates.pop('fixed_ip', None)

        db_floatingip = db.floating_ip_update(self._context, str(self.address),
                                              updates)
        self._from_db_object(self._context, self, db_floatingip)


@obj_base.NovaObjectRegistry.register
class FloatingIPList(obj_base.ObjectListBase, obj_base.NovaObject):
    # Version 1.3: FloatingIP 1.2
    # Version 1.4: FloatingIP 1.3
    # Version 1.5: FloatingIP 1.4
    # Version 1.6: FloatingIP 1.5
    # Version 1.7: FloatingIP 1.6
    # Version 1.8: FloatingIP 1.7
    # Version 1.9: FloatingIP 1.8
    # Version 1.10: FloatingIP 1.9
    # Version 1.11: FloatingIP 1.10
    # Version 1.12: Added get_count_by_project() for quotas
    fields = {
        'objects': fields.ListOfObjectsField('FloatingIP'),
        }
    VERSION = '1.12'

    @staticmethod
    @db_api.pick_context_manager_reader
    def _get_count_by_project_from_db(context, project_id):
        return context.session.query(models.FloatingIp.id).\
                filter_by(deleted=0).\
                filter_by(project_id=project_id).\
                filter_by(auto_assigned=False).\
                count()

    @obj_base.remotable_classmethod
    def get_all(cls, context):
        db_floatingips = db.floating_ip_get_all(context)
        return obj_base.obj_make_list(context, cls(context),
                                      objects.FloatingIP, db_floatingips)

    @obj_base.remotable_classmethod
    def get_by_host(cls, context, host):
        db_floatingips = db.floating_ip_get_all_by_host(context, host)
        return obj_base.obj_make_list(context, cls(context),
                                      objects.FloatingIP, db_floatingips)

    @obj_base.remotable_classmethod
    def get_by_project(cls, context, project_id):
        db_floatingips = db.floating_ip_get_all_by_project(context, project_id)
        return obj_base.obj_make_list(context, cls(context),
                                      objects.FloatingIP, db_floatingips)

    @obj_base.remotable_classmethod
    def get_by_fixed_address(cls, context, fixed_address):
        db_floatingips = db.floating_ip_get_by_fixed_address(
            context, str(fixed_address))
        return obj_base.obj_make_list(context, cls(context),
                                      objects.FloatingIP, db_floatingips)

    @obj_base.remotable_classmethod
    def get_by_fixed_ip_id(cls, context, fixed_ip_id):
        db_floatingips = db.floating_ip_get_by_fixed_ip_id(context,
                                                           fixed_ip_id)
        return obj_base.obj_make_list(context, cls(), FloatingIP,
                                      db_floatingips)

    @staticmethod
    def make_ip_info(address, pool, interface):
        return {'address': str(address),
                'pool': pool,
                'interface': interface}

    @obj_base.remotable_classmethod
    def create(cls, context, ip_info, want_result=False):
        db_floatingips = db.floating_ip_bulk_create(context, ip_info,
                                                    want_result=want_result)
        if want_result:
            return obj_base.obj_make_list(context, cls(), FloatingIP,
                                          db_floatingips)

    @obj_base.remotable_classmethod
    def destroy(cls, context, ips):
        db.floating_ip_bulk_destroy(context, ips)

    @obj_base.remotable_classmethod
    def get_count_by_project(cls, context, project_id):
        return cls._get_count_by_project_from_db(context, project_id)


# We don't want to register this object because it will not be passed
# around on RPC, it just makes our lives a lot easier in the API when
# dealing with floating IP operations
@obj_base.NovaObjectRegistry.register_if(False)
class NeutronFloatingIP(FloatingIP):
    # Version 1.0: Initial Version
    VERSION = '1.0'
    fields = {
        'id': fields.UUIDField(),
        'fixed_ip_id': fields.UUIDField(nullable=True)
    }
