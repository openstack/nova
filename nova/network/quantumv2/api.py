# Copyright 2012 OpenStack LLC.
# All Rights Reserved
# Copyright (c) 2012 NEC Corporation
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
#
# vim: tabstop=4 shiftwidth=4 softtabstop=4

from nova.db import base
from nova import exception
from nova import flags
from nova.network.api import refresh_cache
from nova.network import model as network_model
from nova.network import quantumv2
from nova.openstack.common import cfg
from nova.openstack.common import excutils
from nova.openstack.common import log as logging
from nova import utils


quantum_opts = [
    cfg.StrOpt('quantum_url',
               default='http://127.0.0.1:9696',
               help='URL for connecting to quantum'),
    cfg.IntOpt('quantum_url_timeout',
               default=30,
               help='timeout value for connecting to quantum in seconds'),
    cfg.StrOpt('quantum_admin_username',
               help='username for connecting to quantum in admin context'),
    cfg.StrOpt('quantum_admin_password',
               help='password for connecting to quantum in admin context'),
    cfg.StrOpt('quantum_admin_tenant_name',
               help='tenant name for connecting to quantum in admin context'),
    cfg.StrOpt('quantum_admin_auth_url',
               default='http://localhost:5000/v2.0',
               help='auth url for connecting to quantum in admin context'),
    cfg.StrOpt('quantum_auth_strategy',
               default='keystone',
               help='auth strategy for connecting to '
                    'quantum in admin context'),
    ]

flags.DECLARE('default_floating_pool', 'nova.network.manager')

FLAGS = flags.FLAGS
FLAGS.register_opts(quantum_opts)
LOG = logging.getLogger(__name__)

NET_EXTERNAL = 'router:external'


class API(base.Base):
    """API for interacting with the quantum 2.x API."""

    security_group_api = None

    def setup_networks_on_host(self, context, instance, host=None,
                               teardown=False):
        """Setup or teardown the network structures."""

    def _get_available_networks(self, context, project_id,
                                net_ids=None):
        """Return a network list available for the tenant.
        The list contains networks owned by the tenant and public networks.
        If net_ids specified, it searches networks with requested IDs only.
        """
        quantum = quantumv2.get_client(context)

        # If user has specified to attach instance only to specific
        # networks, add them to **search_opts
        # (1) Retrieve non-public network list owned by the tenant.
        search_opts = {"tenant_id": project_id, 'shared': False}
        if net_ids:
            search_opts['id'] = net_ids
        nets = quantum.list_networks(**search_opts).get('networks', [])
        # (2) Retrieve public network list.
        search_opts = {'shared': True}
        if net_ids:
            search_opts['id'] = net_ids
        nets += quantum.list_networks(**search_opts).get('networks', [])

        _ensure_requested_network_ordering(
            lambda x: x['id'],
            nets,
            net_ids)

        return nets

    def allocate_for_instance(self, context, instance, **kwargs):
        """Allocate all network resources for the instance."""
        quantum = quantumv2.get_client(context)
        LOG.debug(_('allocate_for_instance() for %s'),
                  instance['display_name'])
        if not instance['project_id']:
            msg = _('empty project id for instance %s')
            raise exception.InvalidInput(
                reason=msg % instance['display_name'])
        requested_networks = kwargs.get('requested_networks')
        ports = {}
        fixed_ips = {}
        net_ids = []
        if requested_networks:
            for network_id, fixed_ip, port_id in requested_networks:
                if port_id:
                    port = quantum.show_port(port_id).get('port')
                    network_id = port['network_id']
                    ports[network_id] = port
                elif fixed_ip:
                    fixed_ips[network_id] = fixed_ip
                net_ids.append(network_id)

        nets = self._get_available_networks(context, instance['project_id'],
                                            net_ids)

        touched_port_ids = []
        created_port_ids = []
        for network in nets:
            network_id = network['id']
            zone = 'compute:%s' % FLAGS.node_availability_zone
            port_req_body = {'port': {'device_id': instance['uuid'],
                                      'device_owner': zone}}
            try:
                port = ports.get(network_id)
                if port:
                    quantum.update_port(port['id'], port_req_body)
                    touched_port_ids.append(port['id'])
                else:
                    if fixed_ips.get(network_id):
                        port_req_body['port']['fixed_ips'] = [{'ip_address':
                                                               fixed_ip}]
                    port_req_body['port']['network_id'] = network_id
                    port_req_body['port']['admin_state_up'] = True
                    port_req_body['port']['tenant_id'] = instance['project_id']
                    created_port_ids.append(
                        quantum.create_port(port_req_body)['port']['id'])
            except Exception:
                with excutils.save_and_reraise_exception():
                    for port_id in touched_port_ids:
                        port_in_server = quantum.show_port(port_id).get('port')
                        if not port_in_server:
                            raise Exception('Port have already lost')
                        port_req_body = {'port': {'device_id': None}}
                        quantum.update_port(port_id, port_req_body)

                    for port_id in created_port_ids:
                        try:
                            quantum.delete_port(port_id)
                        except Exception as ex:
                            msg = _("Fail to delete port %(portid)s with"
                                    " failure: %(exception)s")
                            LOG.debug(msg, {'portid': port_id,
                                            'exception': ex})

        self.trigger_security_group_members_refresh(context, instance)
        self.trigger_instance_add_security_group_refresh(context, instance)

        return self.get_instance_nw_info(context, instance, networks=nets)

    def deallocate_for_instance(self, context, instance, **kwargs):
        """Deallocate all network resources related to the instance."""
        LOG.debug(_('deallocate_for_instance() for %s'),
                  instance['display_name'])
        search_opts = {'device_id': instance['uuid']}
        data = quantumv2.get_client(context).list_ports(**search_opts)
        ports = data.get('ports', [])
        for port in ports:
            try:
                quantumv2.get_client(context).delete_port(port['id'])
            except Exception as ex:
                LOG.exception(_("Failed to delete quantum port %(portid)s ")
                              % {'portid': port['id']})
        self.trigger_security_group_members_refresh(context, instance)
        self.trigger_instance_remove_security_group_refresh(context, instance)

    @refresh_cache
    def get_instance_nw_info(self, context, instance, networks=None):
        return self._get_instance_nw_info(context, instance, networks)

    def _get_instance_nw_info(self, context, instance, networks=None):
        LOG.debug(_('get_instance_nw_info() for %s'),
                  instance['display_name'])
        nw_info = self._build_network_info_model(context, instance, networks)
        return network_model.NetworkInfo.hydrate(nw_info)

    def add_fixed_ip_to_instance(self, context, instance, network_id):
        """Add a fixed ip to the instance from specified network."""
        raise NotImplementedError()

    def remove_fixed_ip_from_instance(self, context, instance, address):
        """Remove a fixed ip from the instance."""
        raise NotImplementedError()

    def validate_networks(self, context, requested_networks):
        """Validate that the tenant can use the requested networks."""
        LOG.debug(_('validate_networks() for %s'),
                  requested_networks)
        if not requested_networks:
            return
        net_ids = []

        for (net_id, _i, port_id) in requested_networks:
            if not port_id:
                net_ids.append(net_id)
                continue
            port = quantumv2.get_client(context).show_port(port_id).get('port')
            if not port:
                raise exception.PortNotFound(port_id=port_id)
            if port.get('device_id', None):
                raise exception.PortInUse(port_id=port_id)
            net_id = port['network_id']
            if net_id in net_ids:
                raise exception.NetworkDuplicated(network_id=net_id)
            net_ids.append(net_id)

        nets = self._get_available_networks(context, context.project_id,
                                            net_ids)
        if len(nets) != len(net_ids):
            requsted_netid_set = set(net_ids)
            returned_netid_set = set([net['id'] for net in nets])
            lostid_set = requsted_netid_set - returned_netid_set
            id_str = ''
            for _id in lostid_set:
                id_str = id_str and id_str + ', ' + _id or _id
            raise exception.NetworkNotFound(network_id=id_str)

    def _get_instance_uuids_by_ip(self, context, address):
        """Retrieve instance uuids associated with the given ip address.

        :returns: A list of dicts containing the uuids keyed by 'instance_uuid'
                  e.g. [{'instance_uuid': uuid}, ...]
        """
        search_opts = {"fixed_ips": 'ip_address=%s' % address}
        data = quantumv2.get_client(context).list_ports(**search_opts)
        ports = data.get('ports', [])
        return [{'instance_uuid': port['device_id']} for port in ports
                if port['device_id']]

    def get_instance_uuids_by_ip_filter(self, context, filters):
        """Return a list of dicts in the form of
        [{'instance_uuid': uuid}] that matched the ip filter.
        """
        # filters['ip'] is composed as '^%s$' % fixed_ip.replace('.', '\\.')
        ip = filters.get('ip')
        # we remove ^$\ in the ip filer
        if ip[0] == '^':
            ip = ip[1:]
        if ip[-1] == '$':
            ip = ip[:-1]
        ip = ip.replace('\\.', '.')
        return self._get_instance_uuids_by_ip(context, ip)

    def trigger_instance_add_security_group_refresh(self, context,
                                                    instance_ref):
        # used to avoid circular import
        if not self.security_group_api:
            from nova.compute import api as compute_api
            self.security_group_api = compute_api.SecurityGroupAPI()

        admin_context = context.elevated()
        for group in instance_ref['security_groups']:
            self.security_group_api.trigger_handler(
                'instance_add_security_group', context, instance_ref,
                 group['name'])

    def trigger_instance_remove_security_group_refresh(self, context,
                                                       instance_ref):
        # used to avoid circular import
        if not self.security_group_api:
            from nova.compute import api as compute_api
            self.security_group_api = compute_api.SecurityGroupAPI()

        admin_context = context.elevated()
        for group in instance_ref['security_groups']:
            self.security_group_api.trigger_handler(
                'instance_remove_security_group', context, instance_ref,
                 group['name'])

    def trigger_security_group_members_refresh(self, context, instance_ref):

        # used to avoid circular import
        if not self.security_group_api:
            from nova.compute import api as compute_api
            self.security_group_api = compute_api.SecurityGroupAPI()

        admin_context = context.elevated()
        group_ids = [group['id'] for group in instance_ref['security_groups']]

        self.security_group_api.trigger_members_refresh(admin_context,
                                                        group_ids)
        self.security_group_api.trigger_handler('security_group_members',
                                                admin_context, group_ids)

    def _get_port_id_by_fixed_address(self, client,
                                      instance, address):
        zone = 'compute:%s' % FLAGS.node_availability_zone
        search_opts = {'device_id': instance['uuid'],
                       'device_owner': zone}
        data = client.list_ports(**search_opts)
        ports = data['ports']
        port_id = None
        for p in ports:
            for ip in p['fixed_ips']:
                if ip['ip_address'] == address:
                    port_id = p['id']
                    break
        if not port_id:
            raise exception.FixedIpNotFoundForAddress(address=address)
        return port_id

    @refresh_cache
    def associate_floating_ip(self, context, instance,
                              floating_address, fixed_address,
                              affect_auto_assigned=False):
        """Associate a floating ip with a fixed ip."""

        # Note(amotoki): 'affect_auto_assigned' is not respected
        # since it is not used anywhere in nova code and I could
        # find why this parameter exists.

        client = quantumv2.get_client(context)
        port_id = self._get_port_id_by_fixed_address(client, instance,
                                                     fixed_address)
        fip = self._get_floating_ip_by_address(client, floating_address)
        param = {'port_id': port_id,
                 'fixed_ip_address': fixed_address}
        client.update_floatingip(fip['id'], {'floatingip': param})

    def get_all(self, context):
        raise NotImplementedError()

    def get(self, context, network_uuid):
        raise NotImplementedError()

    def delete(self, context, network_uuid):
        raise NotImplementedError()

    def disassociate(self, context, network_uuid):
        raise NotImplementedError()

    def get_fixed_ip(self, context, id):
        raise NotImplementedError()

    def get_fixed_ip_by_address(self, context, address):
        uuid_maps = self._get_instance_uuids_by_ip(context, address)
        if len(uuid_maps) == 1:
            return uuid_maps[0]
        elif not uuid_maps:
            raise exception.FixedIpNotFoundForAddress(address=address)
        else:
            raise exception.FixedIpAssociatedWithMultipleInstances(
                address=address)

    def _setup_net_dict(self, client, network_id):
        if not network_id:
            return {}
        pool = client.show_network(network_id)['network']
        return {pool['id']: pool}

    def _setup_port_dict(self, client, port_id):
        if not port_id:
            return {}
        port = client.show_port(port_id)['port']
        return {port['id']: port}

    def _setup_pools_dict(self, client):
        pools = self._get_floating_ip_pools(client)
        return dict([(i['id'], i) for i in pools])

    def _setup_ports_dict(self, client, project_id=None):
        search_opts = {'tenant_id': project_id} if project_id else {}
        ports = client.list_ports(**search_opts)['ports']
        return dict([(p['id'], p) for p in ports])

    def get_floating_ip(self, context, id):
        client = quantumv2.get_client(context)
        fip = client.show_floatingip(id)['floatingip']
        pool_dict = self._setup_net_dict(client,
                                         fip['floating_network_id'])
        port_dict = self._setup_port_dict(client, fip['port_id'])
        return self._format_floating_ip_model(fip, pool_dict, port_dict)

    def _get_floating_ip_pools(self, client, project_id=None):
        search_opts = {NET_EXTERNAL: True}
        if project_id:
            search_opts.update({'tenant_id': project_id})
        data = client.list_networks(**search_opts)
        return data['networks']

    def get_floating_ip_pools(self, context):
        client = quantumv2.get_client(context)
        pools = self._get_floating_ip_pools(client)
        return [{'name': n['name'] or n['id']} for n in pools]

    def _format_floating_ip_model(self, fip, pool_dict, port_dict):
        pool = pool_dict[fip['floating_network_id']]
        result = {'id': fip['id'],
                  'address': fip['floating_ip_address'],
                  'pool': pool['name'] or pool['id'],
                  'project_id': fip['tenant_id'],
                  # In Quantum v2, an exact fixed_ip_id does not exist.
                  'fixed_ip_id': fip['port_id'],
                  }
        # In Quantum v2 API fixed_ip_address and instance uuid
        # (= device_id) are known here, so pass it as a result.
        result['fixed_ip'] = {'address': fip['fixed_ip_address']}
        if fip['port_id']:
            instance_uuid = port_dict[fip['port_id']]['device_id']
            result['instance'] = {'uuid': instance_uuid}
        else:
            result['instance'] = None
        return result

    def get_floating_ip_by_address(self, context, address):
        client = quantumv2.get_client(context)
        fip = self._get_floating_ip_by_address(client, address)
        pool_dict = self._setup_net_dict(client,
                                         fip['floating_network_id'])
        port_dict = self._setup_port_dict(client, fip['port_id'])
        return self._format_floating_ip_model(fip, pool_dict, port_dict)

    def get_floating_ips_by_project(self, context):
        client = quantumv2.get_client(context)
        project_id = context.project_id
        fips = client.list_floatingips(tenant_id=project_id)['floatingips']
        pool_dict = self._setup_pools_dict(client)
        port_dict = self._setup_ports_dict(client, project_id)
        return [self._format_floating_ip_model(fip, pool_dict, port_dict)
                for fip in fips]

    def get_floating_ips_by_fixed_address(self, context, fixed_address):
        return []

    def get_instance_id_by_floating_address(self, context, address):
        """Returns the instance id a floating ip's fixed ip is allocated to"""
        client = quantumv2.get_client(context)
        fip = self._get_floating_ip_by_address(client, address)
        if not fip['port_id']:
            return None
        port = client.show_port(fip['port_id'])['port']
        return port['device_id']

    def get_vifs_by_instance(self, context, instance):
        raise NotImplementedError()

    def get_vif_by_mac_address(self, context, mac_address):
        raise NotImplementedError()

    def _get_floating_ip_pool_id_by_name_or_id(self, client, name_or_id):
        search_opts = {NET_EXTERNAL: True, 'fields': 'id'}
        if utils.is_uuid_like(name_or_id):
            search_opts.update({'id': name_or_id})
        else:
            search_opts.update({'name': name_or_id})
        data = client.list_networks(**search_opts)
        nets = data['networks']

        if len(nets) == 1:
            return nets[0]['id']
        elif len(nets) == 0:
            raise exception.FloatingIpPoolNotFound()
        else:
            msg = (_("Multiple floating IP pools matches found for name '%s'")
                   % name_or_id)
            raise exception.NovaException(message=msg)

    def allocate_floating_ip(self, context, pool=None):
        """Add a floating ip to a project from a pool."""
        client = quantumv2.get_client(context)
        pool = pool or FLAGS.default_floating_pool
        pool_id = self._get_floating_ip_pool_id_by_name_or_id(client, pool)

        # TODO(amotoki): handle exception during create_floatingip()
        # At this timing it is ensured that a network for pool exists.
        # quota error may be returned.
        param = {'floatingip': {'floating_network_id': pool_id}}
        fip = client.create_floatingip(param)
        return fip['floatingip']['floating_ip_address']

    def _get_floating_ip_by_address(self, client, address):
        """Get floatingip from floating ip address"""
        data = client.list_floatingips(floating_ip_address=address)
        fips = data['floatingips']
        if len(fips) == 0:
            raise exception.FloatingIpNotFoundForAddress(address=address)
        elif len(fips) > 1:
            raise exception.FloatingIpMultipleFoundForAddress(address=address)
        return fips[0]

    def release_floating_ip(self, context, address,
                            affect_auto_assigned=False):
        """Remove a floating ip with the given address from a project."""

        # Note(amotoki): We cannot handle a case where multiple pools
        # have overlapping IP address range. In this case we cannot use
        # 'address' as a unique key.
        # This is a limitation of the current nova.

        # Note(amotoki): 'affect_auto_assigned' is not respected
        # since it is not used anywhere in nova code and I could
        # find why this parameter exists.

        client = quantumv2.get_client(context)
        fip = self._get_floating_ip_by_address(client, address)
        if fip['port_id']:
            raise exception.FloatingIpAssociated(address=address)
        client.delete_floatingip(fip['id'])

    @refresh_cache
    def disassociate_floating_ip(self, context, instance, address,
                                 affect_auto_assigned=False):
        """Disassociate a floating ip from the instance."""

        # Note(amotoki): 'affect_auto_assigned' is not respected
        # since it is not used anywhere in nova code and I could
        # find why this parameter exists.

        client = quantumv2.get_client(context)
        fip = self._get_floating_ip_by_address(client, address)
        client.update_floatingip(fip['id'], {'floatingip': {'port_id': None}})

    def add_network_to_project(self, context, project_id, network_uuid=None):
        """Force add a network to the project."""
        raise NotImplementedError()

    def _build_network_info_model(self, context, instance, networks=None):
        search_opts = {'tenant_id': instance['project_id'],
                       'device_id': instance['uuid'], }
        data = quantumv2.get_client(context).list_ports(**search_opts)
        ports = data.get('ports', [])
        if not networks:
            networks = self._get_available_networks(context,
                                                    instance['project_id'])
        else:
            # ensure ports are in preferred network order
            _ensure_requested_network_ordering(
                lambda x: x['network_id'],
                ports,
                [n['id'] for n in networks])

        nw_info = network_model.NetworkInfo()
        for port in ports:
            network_name = None
            for net in networks:
                if port['network_id'] == net['id']:
                    network_name = net['name']
                    break

            network_IPs = [network_model.FixedIP(address=ip_address)
                           for ip_address in [ip['ip_address']
                                              for ip in port['fixed_ips']]]
            # TODO(gongysh) get floating_ips for each fixed_ip

            subnets = self._get_subnets_from_port(context, port)
            for subnet in subnets:
                subnet['ips'] = [fixed_ip for fixed_ip in network_IPs
                                 if fixed_ip.is_in_subnet(subnet)]

            network = network_model.Network(
                id=port['network_id'],
                bridge='',  # Quantum ignores this field
                injected=FLAGS.flat_injected,
                label=network_name,
                tenant_id=net['tenant_id']
            )
            network['subnets'] = subnets
            nw_info.append(network_model.VIF(
                id=port['id'],
                address=port['mac_address'],
                network=network))
        return nw_info

    def _get_subnets_from_port(self, context, port):
        """Return the subnets for a given port."""

        fixed_ips = port['fixed_ips']
        # No fixed_ips for the port means there is no subnet associated
        # with the network the port is created on.
        # Since list_subnets(id=[]) returns all subnets visible for the
        # current tenant, returned subnets may contain subnets which is not
        # related to the port. To avoid this, the method returns here.
        if not fixed_ips:
            return []
        search_opts = {'id': [ip['subnet_id'] for ip in fixed_ips]}
        data = quantumv2.get_client(context).list_subnets(**search_opts)
        ipam_subnets = data.get('subnets', [])
        subnets = []

        for subnet in ipam_subnets:
            subnet_dict = {'cidr': subnet['cidr'],
                           'gateway': network_model.IP(
                                address=subnet['gateway_ip'],
                                type='gateway'),
            }

            # attempt to populate DHCP server field
            search_opts = {'network_id': subnet['network_id'],
                           'device_owner': 'network:dhcp'}
            data = quantumv2.get_client(context).list_ports(**search_opts)
            dhcp_ports = data.get('ports', [])
            for p in dhcp_ports:
                for ip_pair in p['fixed_ips']:
                    if ip_pair['subnet_id'] == subnet['id']:
                        subnet_dict['dhcp_server'] = ip_pair['ip_address']
                        break

            subnet_object = network_model.Subnet(**subnet_dict)
            for dns in subnet.get('dns_nameservers', []):
                subnet_object.add_dns(
                    network_model.IP(address=dns, type='dns'))

            # TODO(gongysh) get the routes for this subnet
            subnets.append(subnet_object)
        return subnets

    def get_dns_domains(self, context):
        """Return a list of available dns domains.

        These can be used to create DNS entries for floating ips.
        """
        raise NotImplementedError()

    def add_dns_entry(self, context, address, name, dns_type, domain):
        """Create specified DNS entry for address."""
        raise NotImplementedError()

    def modify_dns_entry(self, context, name, address, domain):
        """Create specified DNS entry for address."""
        raise NotImplementedError()

    def delete_dns_entry(self, context, name, domain):
        """Delete the specified dns entry."""
        raise NotImplementedError()

    def delete_dns_domain(self, context, domain):
        """Delete the specified dns domain."""
        raise NotImplementedError()

    def get_dns_entries_by_address(self, context, address, domain):
        """Get entries for address and domain."""
        raise NotImplementedError()

    def get_dns_entries_by_name(self, context, name, domain):
        """Get entries for name and domain."""
        raise NotImplementedError()

    def create_private_dns_domain(self, context, domain, availability_zone):
        """Create a private DNS domain with nova availability zone."""
        raise NotImplementedError()

    def create_public_dns_domain(self, context, domain, project=None):
        """Create a private DNS domain with optional nova project."""
        raise NotImplementedError()


def _ensure_requested_network_ordering(accessor, unordered, preferred):
    """Sort a list with respect to the preferred network ordering."""
    if preferred:
        unordered.sort(key=lambda i: preferred.index(accessor(i)))
