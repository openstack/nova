# Copyright 2012 OpenStack LLC.
# All Rights Reserved
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

FLAGS = flags.FLAGS
FLAGS.register_opts(quantum_opts)

LOG = logging.getLogger(__name__)


class API(base.Base):
    """API for interacting with the quantum 2.x API."""

    def setup_networks_on_host(self, context, instance, host=None,
                               teardown=False):
        """Setup or teardown the network structures."""

    def allocate_for_instance(self, context, instance, **kwargs):
        """Allocate all network resources for the instance."""
        LOG.debug(_('allocate_for_instance() for %s'),
                  instance['display_name'])
        search_opts = {}
        if instance['project_id']:
            search_opts.update({"tenant_id": instance['project_id']})
        else:
            msg = _('empty project id for instance %s')
            raise exception.InvalidInput(
                reason=msg % instance['display_name'])
        data = quantumv2.get_client(context).list_networks(**search_opts)
        nets = data.get('networks', [])
        created_port_ids = []
        for network in nets:
            port_req_body = {'port': {'network_id': network['id'],
                                      'admin_state_up': True,
                                      'device_id': instance['uuid'],
                                      'tenant_id': instance['project_id']},
            }
            try:
                created_port_ids.append(
                    quantumv2.get_client(context).create_port(
                        port_req_body)['port']['id'])
            except Exception:
                with excutils.save_and_reraise_exception():
                    for port_id in created_port_ids:
                        try:
                            quantumv2.get_client(context).delete_port(port_id)
                        except Exception as ex:
                            msg = _("Fail to delete port %(portid)s with"
                                    " failure: %(exception)s")
                            LOG.debug(msg, {'portid': port_id,
                                            'exception': ex})
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
                with excutils.save_and_reraise_exception():
                    msg = _("Fail to delete port %(portid)s with failure:"
                            "%(exception)s")
                    LOG.debug(msg, {'portid': port['id'],
                                    'exception': ex})

    @refresh_cache
    def get_instance_nw_info(self, context, instance, networks=None):
        LOG.debug(_('get_instance_nw_info() for %s'),
                  instance['display_name'])
        nw_info = self._build_network_info_model(context, instance, networks)
        return network_model.NetworkInfo.hydrate(nw_info)

    def add_fixed_ip_to_instance(self, context, instance, network_id):
        """Add a fixed ip to the instance from specified network."""
        raise NotImplemented()

    def remove_fixed_ip_from_instance(self, context, instance, address):
        """Remove a fixed ip from the instance."""
        raise NotImplemented()

    def validate_networks(self, context, requested_networks):
        """Validate that the tenant has the requested networks."""
        LOG.debug(_('validate_networks() for %s'),
                  requested_networks)
        if not requested_networks:
            return
        search_opts = {"tenant_id": context.project_id}
        net_ids = [net_id for (net_id, _i) in requested_networks]
        search_opts['id'] = net_ids
        data = quantumv2.get_client(context).list_networks(**search_opts)
        nets = data.get('networks', [])
        if len(nets) != len(net_ids):
            requsted_netid_set = set(net_ids)
            returned_netid_set = set([net['id'] for net in nets])
            lostid_set = requsted_netid_set - returned_netid_set
            id_str = ''
            for _id in lostid_set:
                id_str = id_str and id_str + ', ' + _id or _id
            raise exception.NetworkNotFound(network_id=id_str)

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
        search_opts = {"fixed_ips": {'ip_address': ip}}
        data = quantumv2.get_client(context).list_ports(**search_opts)
        ports = data.get('ports', [])

        return [{'instance_uuid': port['device_id']} for port in ports
                if port['device_id']]

    @refresh_cache
    def associate_floating_ip(self, context, instance,
                              floating_address, fixed_address,
                              affect_auto_assigned=False):
        """Associate a floating ip with a fixed ip."""
        raise NotImplemented()

    def get_all(self, context):
        raise NotImplemented()

    def get(self, context, network_uuid):
        raise NotImplemented()

    def delete(self, context, network_uuid):
        raise NotImplemented()

    def disassociate(self, context, network_uuid):
        raise NotImplemented()

    def get_fixed_ip(self, context, id):
        raise NotImplemented()

    def get_fixed_ip_by_address(self, context, address):
        raise NotImplemented()

    def get_floating_ip(self, context, id):
        raise NotImplemented()

    def get_floating_ip_pools(self, context):
        raise NotImplemented()

    def get_floating_ip_by_address(self, context, address):
        raise NotImplemented()

    def get_floating_ips_by_project(self, context):
        raise NotImplemented()

    def get_floating_ips_by_fixed_address(self, context, fixed_address):
        raise NotImplemented()

    def get_instance_id_by_floating_address(self, context, address):
        raise NotImplemented()

    def get_vifs_by_instance(self, context, instance):
        raise NotImplemented()

    def get_vif_by_mac_address(self, context, mac_address):
        raise NotImplemented()

    def allocate_floating_ip(self, context, pool=None):
        """Add a floating ip to a project from a pool."""
        raise NotImplemented()

    def release_floating_ip(self, context, address,
                            affect_auto_assigned=False):
        """Remove a floating ip with the given address from a project."""
        raise NotImplemented()

    @refresh_cache
    def disassociate_floating_ip(self, context, instance, address,
                                 affect_auto_assigned=False):
        """Disassociate a floating ip from the fixed ip
        it is associated with."""
        raise NotImplemented()

    def add_network_to_project(self, context, project_id):
        """Force add a network to the project."""
        raise NotImplemented()

    def _build_network_info_model(self, context, instance, networks=None):
        search_opts = {'tenant_id': instance['project_id'],
                       'device_id': instance['uuid'], }
        data = quantumv2.get_client(context).list_ports(**search_opts)
        ports = data.get('ports', [])
        if not networks:
            search_opts = {}
            if instance['project_id']:
                search_opts.update({"tenant_id": instance['project_id']})
            data = quantumv2.get_client(context).list_networks(**search_opts)
            networks = data.get('networks', [])
        nw_info = network_model.NetworkInfo()
        for port in ports:
            network_name = None
            for net in networks:
                if port['network_id'] == net['id']:
                    network_name = net['name']
                    break

            subnets = self._get_subnets_from_port(context, port)
            network_IPs = [network_model.FixedIP(address=ip_address)
                           for ip_address in [ip['ip_address']
                                              for ip in port['fixed_ips']]]
            # TODO(gongysh) get floating_ips for each fixed_ip

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
            # TODO(gongysh) deal with dhcp

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
        raise NotImplemented()

    def add_dns_entry(self, context, address, name, dns_type, domain):
        """Create specified DNS entry for address."""
        raise NotImplemented()

    def modify_dns_entry(self, context, name, address, domain):
        """Create specified DNS entry for address."""
        raise NotImplemented()

    def delete_dns_entry(self, context, name, domain):
        """Delete the specified dns entry."""
        raise NotImplemented()

    def delete_dns_domain(self, context, domain):
        """Delete the specified dns domain."""
        raise NotImplemented()

    def get_dns_entries_by_address(self, context, address, domain):
        """Get entries for address and domain."""
        raise NotImplemented()

    def get_dns_entries_by_name(self, context, name, domain):
        """Get entries for name and domain."""
        raise NotImplemented()

    def create_private_dns_domain(self, context, domain, availability_zone):
        """Create a private DNS domain with nova availability zone."""
        raise NotImplemented()

    def create_public_dns_domain(self, context, domain, project=None):
        """Create a private DNS domain with optional nova project."""
        raise NotImplemented()
