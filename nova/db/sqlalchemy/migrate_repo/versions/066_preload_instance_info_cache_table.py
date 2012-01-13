# Copyright 2011 OpenStack LLC.
# All Rights Reserved.
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

import json

from sqlalchemy import *
from migrate import *

from nova import ipv6
from nova import log as logging
from nova import utils

meta = MetaData()


def upgrade(migrate_engine):
    meta.bind = migrate_engine
    # grab tables
    instance_info_caches = Table('instance_info_caches', meta, autoload=True)
    instances = Table('instances', meta, autoload=True)
    vifs = Table('virtual_interfaces', meta, autoload=True)
    networks = Table('networks', meta, autoload=True)
    fixed_ips = Table('fixed_ips', meta, autoload=True)
    floating_ips = Table('floating_ips', meta, autoload=True)

    # all of these functions return a python list of python dicts
    # that have nothing to do with sqlalchemy objects whatsoever
    # after returning
    def get_instances():
        # want all instances whether there is network info or not
        s = select([instances.c.id, instances.c.uuid])
        keys = ('id', 'uuid')

        return [dict(zip(keys, row)) for row in s.execute()]

    def get_vifs_by_instance_id(instance_id):
        s = select([vifs.c.id, vifs.c.uuid, vifs.c.address, vifs.c.network_id],
                   vifs.c.instance_id == instance_id)
        keys = ('id', 'uuid', 'address', 'network_id')
        return [dict(zip(keys, row)) for row in s.execute()]

    def get_network_by_id(network_id):
        s = select([networks.c.uuid, networks.c.label,
                    networks.c.project_id,
                    networks.c.dns1, networks.c.dns2,
                    networks.c.cidr, networks.c.cidr_v6,
                    networks.c.gateway, networks.c.gateway_v6,
                    networks.c.injected, networks.c.multi_host,
                    networks.c.bridge, networks.c.bridge_interface,
                    networks.c.vlan],
                   networks.c.id == network_id)
        keys = ('uuid', 'label', 'project_id', 'dns1', 'dns2',
                'cidr', 'cidr_v6', 'gateway', 'gateway_v6',
                'injected', 'multi_host', 'bridge', 'bridge_interface', 'vlan')
        return [dict(zip(keys, row)) for row in s.execute()]

    def get_fixed_ips_by_vif_id(vif_id):
        s = select([fixed_ips.c.id, fixed_ips.c.address],
                   fixed_ips.c.virtual_interface_id == vif_id)
        keys = ('id', 'address')
        fixed_ip_list = [dict(zip(keys, row)) for row in s.execute()]

        # fixed ips have floating ips, so here they are
        for fixed_ip in fixed_ip_list:
            fixed_ip['version'] = 4
            fixed_ip['floating_ips'] =\
                   get_floating_ips_by_fixed_ip_id(fixed_ip['id'])
            fixed_ip['type'] = 'fixed'
            del fixed_ip['id']

        return fixed_ip_list

    def get_floating_ips_by_fixed_ip_id(fixed_ip_id):
        s = select([floating_ips.c.address],
                   floating_ips.c.fixed_ip_id == fixed_ip_id)
        keys = ('address')
        floating_ip_list = [dict(zip(keys, row)) for row in s.execute()]

        for floating_ip in floating_ip_list:
            floating_ip['version'] = 4
            floating_ip['type'] = 'floating'

        return floating_ip_list

    def _ip_dict_from_string(ip_string, type):
        if ip_string:
            ip = {'address': ip_string,
                  'type': type}
            if ':' in ip_string:
                ip['version'] = 6
            else:
                ip['version'] = 4

            return ip

    def _get_fixed_ipv6_dict(cidr, mac, project_id):
        ip_string = ipv6.to_global(cidr, mac, project_id)
        return {'version': 6,
                'address': ip_string,
                'floating_ips': []}

    def _create_subnet(version, network, vif):
        if version == 4:
            cidr = network['cidr']
            gateway = network['gateway']
            ips = get_fixed_ips_by_vif_id(vif['id'])
        else:
            cidr = network['cidr_v6']
            gateway = network['gateway_v6']
            ips = [_get_fixed_ipv6_dict(network['cidr_v6'],
                                        vif['address'],
                                        network['project_id'])]

        # NOTE(tr3buchet) routes is left empty for now because there
        # is no good way to generate them or determine which is default
        subnet = {'version': version,
                  'cidr': cidr,
                  'dns': [],
                  'gateway': _ip_dict_from_string(gateway, 'gateway'),
                  'routes': [],
                  'ips': ips}

        if network['dns1'] and network['dns1']['version'] == version:
            subnet['dns'].append(network['dns1'])
        if network['dns2'] and network['dns2']['version'] == version:
            subnet['dns'].append(network['dns2'])

        return subnet

    # preload caches table
    # list is made up of a row(instance_id, nw_info_json) for each instance
    for instance in get_instances():
        logging.info("Updating %s" % (instance['uuid']))
        instance_id = instance['id']
        instance_uuid = instance['uuid']

        # instances have vifs so aninstance nw_info is
        # is a list of dicts, 1 dict for each vif
        nw_info = get_vifs_by_instance_id(instance_id)
        logging.info("VIFs for Instance %s: \n %s" % \
                        (instance['uuid'], nw_info))
        for vif in nw_info:
            network = get_network_by_id(vif['network_id'])[0]
            logging.info("Network for Instance %s: \n %s" % \
                        (instance['uuid'], network))

            # vifs have a network which has subnets, so create the subnets
            # subnets contain all of the ip information
            network['subnets'] = []

            network['dns1'] = _ip_dict_from_string(network['dns1'], 'dns')
            network['dns2'] = _ip_dict_from_string(network['dns2'], 'dns')

            # nova networks can only have 2 subnets
            if network['cidr']:
                network['subnets'].append(_create_subnet(4, network, vif))
            if network['cidr_v6']:
                network['subnets'].append(_create_subnet(6, network, vif))

            # put network together to fit model
            network['id'] = network.pop('uuid')
            network['meta'] = {}

            # NOTE(tr3buchet) this isn't absolutely necessary as hydration
            # would still work with these as keys, but cache generated by
            # the model would show these keys as a part of meta. i went
            # ahead and set it up the same way just so it looks the same
            if network['project_id']:
                network['meta']['project_id'] = network['project_id']
            del network['project_id']
            if network['injected']:
                network['meta']['injected'] = network['injected']
            del network['injected']
            if network['multi_host']:
                network['meta']['multi_host'] = network['multi_host']
            del network['multi_host']
            if network['bridge_interface']:
                network['meta']['bridge_interface'] = \
                                                  network['bridge_interface']
            del network['bridge_interface']
            if network['vlan']:
                network['meta']['vlan'] = network['vlan']
            del network['vlan']

            # ip information now lives in the subnet, pull them out of network
            del network['dns1']
            del network['dns2']
            del network['cidr']
            del network['cidr_v6']
            del network['gateway']
            del network['gateway_v6']

            # don't need meta if it's empty
            if not network['meta']:
                del network['meta']

            # put vif together to fit model
            del vif['network_id']
            vif['id'] = vif.pop('uuid')
            vif['network'] = network
            # vif['meta'] could also be set to contain rxtx data here
            # but it isn't exposed in the api and is still being rewritten

            logging.info("VIF network for instance %s: \n %s" % \
                        (instance['uuid'], vif['network']))

        # jsonify nw_info
        row = {'created_at': utils.utcnow(),
               'updated_at': utils.utcnow(),
               'instance_id': instance_uuid,
               'network_info': json.dumps(nw_info)}

        # write write row to table
        insert = instance_info_caches.insert().values(**row)
        migrate_engine.execute(insert)


def downgrade(migrate_engine):
    # facepalm
    meta.bind = migrate_engine
    instance_info_caches = Table('instance_info_caches', meta, autoload=True)

    # there is really no way to know what data was added by the migration and
    # what was added afterward. Of note is the fact that before this migration
    # the cache table was empty; therefore, delete everything. Also, aliens.
    instance_info_caches.delete()
