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

import netaddr
from oslo_config import cfg
from oslo_utils import versionutils

from nova import db
from nova import exception
from nova.i18n import _
from nova import objects
from nova.objects import base as obj_base
from nova.objects import fields

network_opts = [
    cfg.BoolOpt('share_dhcp_address',
                default=False,
                help='DEPRECATED: THIS VALUE SHOULD BE SET WHEN CREATING THE '
                     'NETWORK. If True in multi_host mode, all compute hosts '
                     'share the same dhcp address. The same IP address used '
                     'for DHCP will be added on each nova-network node which '
                     'is only visible to the vms on the same host.'),
    # NOTE(mriedem): Remove network_device_mtu in Newton.
    cfg.IntOpt('network_device_mtu',
               deprecated_for_removal=True,
               help='DEPRECATED: THIS VALUE SHOULD BE SET WHEN CREATING THE '
                    'NETWORK. MTU setting for network interface.'),
]

CONF = cfg.CONF
CONF.register_opts(network_opts)


# TODO(berrange): Remove NovaObjectDictCompat
@obj_base.NovaObjectRegistry.register
class Network(obj_base.NovaPersistentObject, obj_base.NovaObject,
              obj_base.NovaObjectDictCompat):
    # Version 1.0: Initial version
    # Version 1.1: Added in_use_on_host()
    # Version 1.2: Added mtu, dhcp_server, enable_dhcp, share_address
    VERSION = '1.2'

    fields = {
        'id': fields.IntegerField(),
        'label': fields.StringField(),
        'injected': fields.BooleanField(),
        'cidr': fields.IPV4NetworkField(nullable=True),
        'cidr_v6': fields.IPV6NetworkField(nullable=True),
        'multi_host': fields.BooleanField(),
        'netmask': fields.IPV4AddressField(nullable=True),
        'gateway': fields.IPV4AddressField(nullable=True),
        'broadcast': fields.IPV4AddressField(nullable=True),
        'netmask_v6': fields.IPV6AddressField(nullable=True),
        'gateway_v6': fields.IPV6AddressField(nullable=True),
        'bridge': fields.StringField(nullable=True),
        'bridge_interface': fields.StringField(nullable=True),
        'dns1': fields.IPAddressField(nullable=True),
        'dns2': fields.IPAddressField(nullable=True),
        'vlan': fields.IntegerField(nullable=True),
        'vpn_public_address': fields.IPAddressField(nullable=True),
        'vpn_public_port': fields.IntegerField(nullable=True),
        'vpn_private_address': fields.IPAddressField(nullable=True),
        'dhcp_start': fields.IPV4AddressField(nullable=True),
        'rxtx_base': fields.IntegerField(nullable=True),
        'project_id': fields.UUIDField(nullable=True),
        'priority': fields.IntegerField(nullable=True),
        'host': fields.StringField(nullable=True),
        'uuid': fields.UUIDField(),
        'mtu': fields.IntegerField(nullable=True),
        'dhcp_server': fields.IPAddressField(nullable=True),
        'enable_dhcp': fields.BooleanField(),
        'share_address': fields.BooleanField(),
        }

    @staticmethod
    def _convert_legacy_ipv6_netmask(netmask):
        """Handle netmask_v6 possibilities from the database.

        Historically, this was stored as just an integral CIDR prefix,
        but in the future it should be stored as an actual netmask.
        Be tolerant of either here.
        """
        try:
            prefix = int(netmask)
            return netaddr.IPNetwork('1::/%i' % prefix).netmask
        except ValueError:
            pass

        try:
            return netaddr.IPNetwork(netmask).netmask
        except netaddr.AddrFormatError:
            raise ValueError(_('IPv6 netmask "%s" must be a netmask '
                               'or integral prefix') % netmask)

    def obj_make_compatible(self, primitive, target_version):
        target_version = versionutils.convert_version_to_tuple(target_version)
        if target_version < (1, 2):
            if 'mtu' in primitive:
                del primitive['mtu']
            if 'enable_dhcp' in primitive:
                del primitive['enable_dhcp']
            if 'dhcp_server' in primitive:
                del primitive['dhcp_server']
            if 'share_address' in primitive:
                del primitive['share_address']

    @staticmethod
    def _from_db_object(context, network, db_network):
        for field in network.fields:
            db_value = db_network[field]
            if field is 'netmask_v6' and db_value is not None:
                db_value = network._convert_legacy_ipv6_netmask(db_value)
            if field is 'mtu' and db_value is None:
                db_value = CONF.network_device_mtu
            if field is 'dhcp_server' and db_value is None:
                db_value = db_network['gateway']
            if field is 'share_address' and CONF.share_dhcp_address:
                db_value = CONF.share_dhcp_address

            network[field] = db_value
        network._context = context
        network.obj_reset_changes()
        return network

    @obj_base.remotable_classmethod
    def get_by_id(cls, context, network_id, project_only='allow_none'):
        db_network = db.network_get(context, network_id,
                                    project_only=project_only)
        return cls._from_db_object(context, cls(), db_network)

    @obj_base.remotable_classmethod
    def get_by_uuid(cls, context, network_uuid):
        db_network = db.network_get_by_uuid(context, network_uuid)
        return cls._from_db_object(context, cls(), db_network)

    @obj_base.remotable_classmethod
    def get_by_cidr(cls, context, cidr):
        db_network = db.network_get_by_cidr(context, cidr)
        return cls._from_db_object(context, cls(), db_network)

    @obj_base.remotable_classmethod
    def associate(cls, context, project_id, network_id=None, force=False):
        db.network_associate(context, project_id, network_id=network_id,
                             force=force)

    @obj_base.remotable_classmethod
    def disassociate(cls, context, network_id, host=False, project=False):
        db.network_disassociate(context, network_id, host, project)

    @obj_base.remotable_classmethod
    def in_use_on_host(cls, context, network_id, host):
        return db.network_in_use_on_host(context, network_id, host)

    def _get_primitive_changes(self):
        changes = {}
        for key, value in self.obj_get_changes().items():
            if isinstance(value, netaddr.IPAddress):
                changes[key] = str(value)
            else:
                changes[key] = value
        return changes

    @obj_base.remotable
    def create(self):
        updates = self._get_primitive_changes()
        if 'id' in updates:
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        db_network = db.network_create_safe(self._context, updates)
        self._from_db_object(self._context, self, db_network)

    @obj_base.remotable
    def destroy(self):
        db.network_delete_safe(self._context, self.id)
        self.deleted = True
        self.obj_reset_changes(['deleted'])

    @obj_base.remotable
    def save(self):
        context = self._context
        updates = self._get_primitive_changes()
        if 'netmask_v6' in updates:
            # NOTE(danms): For some reason, historical code stores the
            # IPv6 netmask as just the CIDR mask length, so convert that
            # back here before saving for now.
            updates['netmask_v6'] = netaddr.IPNetwork(
                updates['netmask_v6']).netmask
        set_host = 'host' in updates
        if set_host:
            db.network_set_host(context, self.id, updates.pop('host'))
        if updates:
            db_network = db.network_update(context, self.id, updates)
        elif set_host:
            db_network = db.network_get(context, self.id)
        else:
            db_network = None
        if db_network is not None:
            self._from_db_object(context, self, db_network)


@obj_base.NovaObjectRegistry.register
class NetworkList(obj_base.ObjectListBase, obj_base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: Added get_by_project()
    # Version 1.2: Network <= version 1.2
    VERSION = '1.2'

    fields = {
        'objects': fields.ListOfObjectsField('Network'),
        }

    @obj_base.remotable_classmethod
    def get_all(cls, context, project_only='allow_none'):
        db_networks = db.network_get_all(context, project_only)
        return obj_base.obj_make_list(context, cls(context), objects.Network,
                                      db_networks)

    @obj_base.remotable_classmethod
    def get_by_uuids(cls, context, network_uuids, project_only='allow_none'):
        db_networks = db.network_get_all_by_uuids(context, network_uuids,
                                                  project_only)
        return obj_base.obj_make_list(context, cls(context), objects.Network,
                                      db_networks)

    @obj_base.remotable_classmethod
    def get_by_host(cls, context, host):
        db_networks = db.network_get_all_by_host(context, host)
        return obj_base.obj_make_list(context, cls(context), objects.Network,
                                      db_networks)

    @obj_base.remotable_classmethod
    def get_by_project(cls, context, project_id, associate=True):
        db_networks = db.project_get_networks(context, project_id,
                                              associate=associate)
        return obj_base.obj_make_list(context, cls(context), objects.Network,
                                      db_networks)
