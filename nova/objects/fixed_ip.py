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

from nova import db
from nova import exception
from nova import objects
from nova.objects import base as obj_base
from nova.objects import fields
from nova.openstack.common import timeutils
from nova import utils


FIXED_IP_OPTIONAL_ATTRS = ['instance', 'network']


class FixedIP(obj_base.NovaPersistentObject, obj_base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Added virtual_interface field
    # Version 1.2: Instance version 1.14
    # Version 1.3: Instance 1.15
    # Version 1.4: Added default_route field
    VERSION = '1.4'

    fields = {
        'id': fields.IntegerField(),
        'address': fields.IPV4AndV6AddressField(),
        'network_id': fields.IntegerField(nullable=True),
        'virtual_interface_id': fields.IntegerField(nullable=True),
        'instance_uuid': fields.UUIDField(nullable=True),
        'allocated': fields.BooleanField(),
        'leased': fields.BooleanField(),
        'reserved': fields.BooleanField(),
        'host': fields.StringField(nullable=True),
        'default_route': fields.BooleanField(),
        'instance': fields.ObjectField('Instance', nullable=True),
        'network': fields.ObjectField('Network', nullable=True),
        'virtual_interface': fields.ObjectField('VirtualInterface',
                                                nullable=True),
        }

    def obj_make_compatible(self, primitive, target_version):
        target_version = utils.convert_version_to_tuple(target_version)
        if target_version < (1, 4) and 'default_route' in primitive:
            del primitive['default_route']
        if target_version < (1, 3) and 'instance' in primitive:
            self.instance.obj_make_compatible(primitive['instance'], '1.14')
            primitive['instance']['nova_object.version'] = '1.14'
        if target_version < (1, 2) and 'instance' in primitive:
            self.instance.obj_make_compatible(primitive['instance'], '1.13')
            primitive['instance']['nova_object.version'] = '1.13'

    @property
    def floating_ips(self):
        return objects.FloatingIPList.get_by_fixed_ip_id(self._context,
                                                         self.id)

    @staticmethod
    def _from_db_object(context, fixedip, db_fixedip, expected_attrs=None):
        if expected_attrs is None:
            expected_attrs = []
        for field in fixedip.fields:
            if field in ('virtual_interface', 'default_route'):
                # NOTE(danms): These fields are only set when doing a
                # FixedIPList.get_by_network() because it's a relatively
                # special-case thing, so skip them here
                continue
            if field not in FIXED_IP_OPTIONAL_ATTRS:
                fixedip[field] = db_fixedip[field]
        # NOTE(danms): Instance could be deleted, and thus None
        if 'instance' in expected_attrs:
            fixedip.instance = objects.Instance._from_db_object(
                context,
                objects.Instance(context),
                db_fixedip['instance']) if db_fixedip['instance'] else None
        if 'network' in expected_attrs:
            fixedip.network = objects.Network._from_db_object(
                context, objects.Network(context), db_fixedip['network'])
        fixedip._context = context
        fixedip.obj_reset_changes()
        return fixedip

    @obj_base.remotable_classmethod
    def get_by_id(cls, context, id, expected_attrs=None):
        if expected_attrs is None:
            expected_attrs = []
        get_network = 'network' in expected_attrs
        db_fixedip = db.fixed_ip_get(context, id, get_network=get_network)
        return cls._from_db_object(context, cls(context), db_fixedip,
                                   expected_attrs)

    @obj_base.remotable_classmethod
    def get_by_address(cls, context, address, expected_attrs=None):
        if expected_attrs is None:
            expected_attrs = []
        db_fixedip = db.fixed_ip_get_by_address(context, str(address),
                                                columns_to_join=expected_attrs)
        return cls._from_db_object(context, cls(context), db_fixedip,
                                   expected_attrs)

    @obj_base.remotable_classmethod
    def get_by_floating_address(cls, context, address):
        db_fixedip = db.fixed_ip_get_by_floating_address(context, str(address))
        if db_fixedip is not None:
            return cls._from_db_object(context, cls(context), db_fixedip)

    @obj_base.remotable_classmethod
    def get_by_network_and_host(cls, context, network_id, host):
        db_fixedip = db.fixed_ip_get_by_network_host(context, network_id, host)
        return cls._from_db_object(context, cls(context), db_fixedip)

    @obj_base.remotable_classmethod
    def associate(cls, context, address, instance_uuid, network_id=None,
                  reserved=False):
        db_fixedip = db.fixed_ip_associate(context, address, instance_uuid,
                                           network_id=network_id,
                                           reserved=reserved)
        return cls._from_db_object(context, cls(context), db_fixedip)

    @obj_base.remotable_classmethod
    def associate_pool(cls, context, network_id, instance_uuid=None,
                       host=None):
        db_fixedip = db.fixed_ip_associate_pool(context, network_id,
                                                instance_uuid=instance_uuid,
                                                host=host)
        return cls._from_db_object(context, cls(context), db_fixedip)

    @obj_base.remotable_classmethod
    def disassociate_by_address(cls, context, address):
        db.fixed_ip_disassociate(context, address)

    @obj_base.remotable_classmethod
    def _disassociate_all_by_timeout(cls, context, host, time_str):
        time = timeutils.parse_isotime(time_str)
        return db.fixed_ip_disassociate_all_by_timeout(context, host, time)

    @classmethod
    def disassociate_all_by_timeout(cls, context, host, time):
        return cls._disassociate_all_by_timeout(context, host,
                                                timeutils.isotime(time))

    @obj_base.remotable
    def create(self, context):
        updates = self.obj_get_changes()
        if 'id' in updates:
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        if 'address' in updates:
            updates['address'] = str(updates['address'])
        db_fixedip = db.fixed_ip_create(context, updates)
        self._from_db_object(context, self, db_fixedip)

    @obj_base.remotable
    def save(self, context):
        updates = self.obj_get_changes()
        if 'address' in updates:
            raise exception.ObjectActionError(action='save',
                                              reason='address is not mutable')
        db.fixed_ip_update(context, str(self.address), updates)
        self.obj_reset_changes()

    @obj_base.remotable
    def disassociate(self, context):
        db.fixed_ip_disassociate(context, str(self.address))
        self.instance_uuid = None
        self.instance = None
        self.obj_reset_changes(['instance_uuid', 'instance'])


class FixedIPList(obj_base.ObjectListBase, obj_base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Added get_by_network()
    # Version 1.2: FixedIP <= version 1.2
    # Version 1.3: FixedIP <= version 1.3
    # Version 1.4: FixedIP <= version 1.4
    VERSION = '1.4'

    fields = {
        'objects': fields.ListOfObjectsField('FixedIP'),
        }
    child_versions = {
        '1.0': '1.0',
        '1.1': '1.1',
        '1.2': '1.2',
        '1.3': '1.3',
        '1.4': '1.4',
        }

    @obj_base.remotable_classmethod
    def get_all(cls, context):
        db_fixedips = db.fixed_ip_get_all(context)
        return obj_base.obj_make_list(context, cls(context),
                                      objects.FixedIP, db_fixedips)

    @obj_base.remotable_classmethod
    def get_by_instance_uuid(cls, context, instance_uuid):
        db_fixedips = db.fixed_ip_get_by_instance(context, instance_uuid)
        return obj_base.obj_make_list(context, cls(context),
                                      objects.FixedIP, db_fixedips)

    @obj_base.remotable_classmethod
    def get_by_host(cls, context, host):
        db_fixedips = db.fixed_ip_get_by_host(context, host)
        return obj_base.obj_make_list(context, cls(context),
                                      objects.FixedIP, db_fixedips)

    @obj_base.remotable_classmethod
    def get_by_virtual_interface_id(cls, context, vif_id):
        db_fixedips = db.fixed_ips_by_virtual_interface(context, vif_id)
        return obj_base.obj_make_list(context, cls(context),
                                      objects.FixedIP, db_fixedips)

    @obj_base.remotable_classmethod
    def get_by_network(cls, context, network, host=None):
        ipinfo = db.network_get_associated_fixed_ips(context,
                                                     network['id'],
                                                     host=host)
        if not ipinfo:
            return []

        fips = cls(context=context, objects=[])

        for info in ipinfo:
            inst = objects.Instance(context=context,
                                    uuid=info['instance_uuid'],
                                    hostname=info['instance_hostname'],
                                    created_at=info['instance_created'],
                                    updated_at=info['instance_updated'])
            vif = objects.VirtualInterface(context=context,
                                           id=info['vif_id'],
                                           address=info['vif_address'])
            fip = objects.FixedIP(context=context,
                                  address=info['address'],
                                  instance_uuid=info['instance_uuid'],
                                  network_id=info['network_id'],
                                  virtual_interface_id=info['vif_id'],
                                  allocated=info['allocated'],
                                  leased=info['leased'],
                                  default_route=info['default_route'],
                                  instance=inst,
                                  virtual_interface=vif)
            fips.objects.append(fip)
        fips.obj_reset_changes()
        return fips

    @obj_base.remotable_classmethod
    def bulk_create(self, context, fixed_ips):
        ips = []
        for fixedip in fixed_ips:
            ip = obj_base.obj_to_primitive(fixedip)
            if 'id' in ip:
                raise exception.ObjectActionError(action='create',
                                                  reason='already created')
            ips.append(ip)
        db.fixed_ip_bulk_create(context, ips)
