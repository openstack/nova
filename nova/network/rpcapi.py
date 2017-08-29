# Copyright 2013, Red Hat, Inc.
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

"""
Client side of the network RPC API.
"""

import oslo_messaging as messaging
from oslo_serialization import jsonutils

import nova.conf
from nova import exception
from nova.objects import base as objects_base
from nova import profiler
from nova import rpc


CONF = nova.conf.CONF
RPC_TOPIC = 'network'


@profiler.trace_cls("rpc")
class NetworkAPI(object):
    '''Client side of the network rpc API.

    API version history:

        * 1.0 - Initial version.
        * 1.1 - Adds migrate_instance_[start|finish]
        * 1.2 - Make migrate_instance_[start|finish] a little more flexible
        * 1.3 - Adds fanout cast update_dns for multi_host networks
        * 1.4 - Add get_backdoor_port()
        * 1.5 - Adds associate
        * 1.6 - Adds instance_uuid to _{dis,}associate_floating_ip
        * 1.7 - Adds method get_floating_ip_pools to replace get_floating_pools
        * 1.8 - Adds macs to allocate_for_instance
        * 1.9 - Adds rxtx_factor to [add|remove]_fixed_ip, removes
                instance_uuid from allocate_for_instance and
                instance_get_nw_info

        ... Grizzly supports message version 1.9.  So, any changes to existing
        methods in 1.x after that point should be done such that they can
        handle the version_cap being set to 1.9.

        * 1.10- Adds (optional) requested_networks to deallocate_for_instance

        ... Havana supports message version 1.10.  So, any changes to existing
        methods in 1.x after that point should be done such that they can
        handle the version_cap being set to 1.10.

        * NOTE: remove unused method get_vifs_by_instance()
        * NOTE: remove unused method get_vif_by_mac_address()
        * NOTE: remove unused method get_network()
        * NOTE: remove unused method get_all_networks()
        * 1.11 - Add instance to deallocate_for_instance().
                 Remove instance_id, project_id, and host.
        * 1.12 - Add instance to deallocate_fixed_ip()

        ... Icehouse supports message version 1.12.  So, any changes to
        existing methods in 1.x after that point should be done such that they
        can handle the version_cap being set to 1.12.

        * 1.13 - Convert allocate_for_instance()
                 to use NetworkRequestList objects

        ... Juno and Kilo supports message version 1.13.  So, any changes to
        existing methods in 1.x after that point should be done such that they
        can handle the version_cap being set to 1.13.

        * NOTE: remove unused method get_floating_ips_by_fixed_address()
        * NOTE: remove unused method get_instance_uuids_by_ip_filter()
        * NOTE: remove unused method disassociate_network()
        * NOTE: remove unused method get_fixed_ip()
        * NOTE: remove unused method get_fixed_ip_by_address()
        * NOTE: remove unused method get_floating_ip()
        * NOTE: remove unused method get_floating_ip_pools()
        * NOTE: remove unused method get_floating_ip_by_address()
        * NOTE: remove unused method get_floating_ips_by_project()
        * NOTE: remove unused method get_instance_id_by_floating_address()
        * NOTE: remove unused method allocate_floating_ip()
        * NOTE: remove unused method deallocate_floating_ip()
        * NOTE: remove unused method associate_floating_ip()
        * NOTE: remove unused method disassociate_floating_ip()
        * NOTE: remove unused method associate()

        * 1.14 - Add mac parameter to release_fixed_ip().
        * 1.15 - Convert set_network_host() to use Network objects.

        ... Liberty supports message version 1.15.  So, any changes to
        existing methods in 1.x after that point should be done such that they
        can handle the version_cap being set to 1.15.

        * 1.16 - Transfer instance in addition to instance_id in
                 setup_networks_on_host

        ... Mitaka supports message version 1.16.  So, any changes to
        existing methods in 1.x after that point should be done such that they
        can handle the version_cap being set to 1.16.

        * 1.17 - Add method release_dhcp()

        ... Newton and Ocata support message version 1.17.  So, any changes to
        existing methods in 1.x after that point should be done such that they
        can handle the version_cap being set to 1.17.
    '''

    VERSION_ALIASES = {
        'grizzly': '1.9',
        'havana': '1.10',
        'icehouse': '1.12',
        'juno': '1.13',
        'kilo': '1.13',
        'liberty': '1.15',
        'mitaka': '1.16',
        'newton': '1.17',
        'ocata': '1.17',
    }

    def __init__(self, topic=None):
        super(NetworkAPI, self).__init__()
        topic = topic or RPC_TOPIC
        target = messaging.Target(topic=topic, version='1.0')
        version_cap = self.VERSION_ALIASES.get(CONF.upgrade_levels.network,
                                               CONF.upgrade_levels.network)
        serializer = objects_base.NovaObjectSerializer()
        self.client = rpc.get_client(target, version_cap, serializer)

    # TODO(russellb): Convert this to named arguments.  It's a pretty large
    # list, so unwinding it all is probably best done in its own patch so it's
    # easier to review.
    def create_networks(self, ctxt, **kwargs):
        return self.client.call(ctxt, 'create_networks', **kwargs)

    def delete_network(self, ctxt, uuid, fixed_range):
        return self.client.call(ctxt, 'delete_network',
                                uuid=uuid, fixed_range=fixed_range)

    def allocate_for_instance(self, ctxt, instance_id, project_id, host,
                              rxtx_factor, vpn, requested_networks, macs=None,
                              dhcp_options=None):
        # NOTE(mriedem): dhcp_options should be removed in version 2.0
        version = '1.13'
        if not self.client.can_send_version(version):
            version = '1.9'
            if requested_networks:
                requested_networks = requested_networks.as_tuples()

        if CONF.multi_host:
            cctxt = self.client.prepare(version=version, server=host)
        else:
            cctxt = self.client.prepare(version=version)
        return cctxt.call(ctxt, 'allocate_for_instance',
                          instance_id=instance_id, project_id=project_id,
                          host=host, rxtx_factor=rxtx_factor, vpn=vpn,
                          requested_networks=requested_networks,
                          macs=jsonutils.to_primitive(macs))

    def deallocate_for_instance(self, ctxt, instance, requested_networks=None):
        cctxt = self.client
        kwargs = {}
        if self.client.can_send_version('1.11'):
            version = '1.11'
            kwargs['instance'] = instance
            kwargs['requested_networks'] = requested_networks
        else:
            if self.client.can_send_version('1.10'):
                version = '1.10'
                kwargs['requested_networks'] = requested_networks
            else:
                version = '1.0'
            kwargs['host'] = instance.host
            kwargs['instance_id'] = instance.uuid
            kwargs['project_id'] = instance.project_id
        if CONF.multi_host:
            cctxt = cctxt.prepare(server=instance.host, version=version)
        return cctxt.call(ctxt, 'deallocate_for_instance', **kwargs)

    def release_dhcp(self, ctxt, host, dev, address, vif_address):
        if self.client.can_send_version('1.17'):
            cctxt = self.client.prepare(version='1.17', server=host)
            return cctxt.call(ctxt, 'release_dhcp', dev=dev, address=address,
                              vif_address=vif_address)
        else:
            raise exception.RPCPinnedToOldVersion()

    def add_fixed_ip_to_instance(self, ctxt, instance_id, rxtx_factor,
                                 host, network_id):
        cctxt = self.client.prepare(version='1.9')
        return cctxt.call(ctxt, 'add_fixed_ip_to_instance',
                         instance_id=instance_id, rxtx_factor=rxtx_factor,
                         host=host, network_id=network_id)

    def remove_fixed_ip_from_instance(self, ctxt, instance_id, rxtx_factor,
                                      host, address):
        cctxt = self.client.prepare(version='1.9')
        return cctxt.call(ctxt, 'remove_fixed_ip_from_instance',
                          instance_id=instance_id, rxtx_factor=rxtx_factor,
                          host=host, address=address)

    def add_network_to_project(self, ctxt, project_id, network_uuid):
        return self.client.call(ctxt, 'add_network_to_project',
                                project_id=project_id,
                                network_uuid=network_uuid)

    def get_instance_nw_info(self, ctxt, instance_id, rxtx_factor, host,
                             project_id):
        cctxt = self.client.prepare(version='1.9')
        return cctxt.call(ctxt, 'get_instance_nw_info',
                          instance_id=instance_id, rxtx_factor=rxtx_factor,
                          host=host, project_id=project_id)

    def validate_networks(self, ctxt, networks):
        return self.client.call(ctxt, 'validate_networks', networks=networks)

    def get_dns_domains(self, ctxt):
        return self.client.call(ctxt, 'get_dns_domains')

    def add_dns_entry(self, ctxt, address, name, dns_type, domain):
        return self.client.call(ctxt, 'add_dns_entry',
                                address=address, name=name,
                                dns_type=dns_type, domain=domain)

    def modify_dns_entry(self, ctxt, address, name, domain):
        return self.client.call(ctxt, 'modify_dns_entry',
                                address=address, name=name, domain=domain)

    def delete_dns_entry(self, ctxt, name, domain):
        return self.client.call(ctxt, 'delete_dns_entry',
                                name=name, domain=domain)

    def delete_dns_domain(self, ctxt, domain):
        return self.client.call(ctxt, 'delete_dns_domain', domain=domain)

    def get_dns_entries_by_address(self, ctxt, address, domain):
        return self.client.call(ctxt, 'get_dns_entries_by_address',
                                address=address, domain=domain)

    def get_dns_entries_by_name(self, ctxt, name, domain):
        return self.client.call(ctxt, 'get_dns_entries_by_name',
                                name=name, domain=domain)

    def create_private_dns_domain(self, ctxt, domain, av_zone):
        return self.client.call(ctxt, 'create_private_dns_domain',
                                domain=domain, av_zone=av_zone)

    def create_public_dns_domain(self, ctxt, domain, project):
        return self.client.call(ctxt, 'create_public_dns_domain',
                                domain=domain, project=project)

    def setup_networks_on_host(self, ctxt, instance_id, host, teardown,
                               instance):
        # NOTE(tr3buchet): the call is just to wait for completion
        version = '1.16'
        kwargs = {}
        if not self.client.can_send_version(version):
            version = '1.0'
        else:
            kwargs['instance'] = instance
        cctxt = self.client.prepare(version=version)
        return cctxt.call(ctxt, 'setup_networks_on_host',
                          instance_id=instance_id, host=host,
                          teardown=teardown, **kwargs)

    def set_network_host(self, ctxt, network_ref):
        version = '1.15'
        if not self.client.can_send_version(version):
            version = '1.0'
            network_ref = objects_base.obj_to_primitive(network_ref)
        cctxt = self.client.prepare(version=version)
        return cctxt.call(ctxt, 'set_network_host', network_ref=network_ref)

    def rpc_setup_network_on_host(self, ctxt, network_id, teardown, host):
        # NOTE(tr3buchet): the call is just to wait for completion
        cctxt = self.client.prepare(server=host)
        return cctxt.call(ctxt, 'rpc_setup_network_on_host',
                          network_id=network_id, teardown=teardown)

    # NOTE(russellb): Ideally this would not have a prefix of '_' since it is
    # a part of the rpc API. However, this is how it was being called when the
    # 1.0 API was being documented using this client proxy class.  It should be
    # changed if there was ever a 2.0.
    def _rpc_allocate_fixed_ip(self, ctxt, instance_id, network_id, address,
                               vpn, host):
        cctxt = self.client.prepare(server=host)
        return cctxt.call(ctxt, '_rpc_allocate_fixed_ip',
                          instance_id=instance_id, network_id=network_id,
                          address=address, vpn=vpn)

    def deallocate_fixed_ip(self, ctxt, address, host, instance):
        kwargs = {}
        if self.client.can_send_version('1.12'):
            version = '1.12'
            kwargs['instance'] = instance
        else:
            version = '1.0'
        cctxt = self.client.prepare(server=host, version=version)
        return cctxt.call(ctxt, 'deallocate_fixed_ip',
                          address=address, host=host, **kwargs)

    def update_dns(self, ctxt, network_ids):
        cctxt = self.client.prepare(fanout=True, version='1.3')
        cctxt.cast(ctxt, 'update_dns', network_ids=network_ids)

    # NOTE(russellb): Ideally this would not have a prefix of '_' since it is
    # a part of the rpc API. However, this is how it was being called when the
    # 1.0 API was being documented using this client proxy class.  It should be
    # changed if there was ever a 2.0.
    def _associate_floating_ip(self, ctxt, floating_address, fixed_address,
                               interface, host, instance_uuid=None):
        cctxt = self.client.prepare(server=host, version='1.6')
        return cctxt.call(ctxt, '_associate_floating_ip',
                          floating_address=floating_address,
                          fixed_address=fixed_address,
                          interface=interface, instance_uuid=instance_uuid)

    # NOTE(russellb): Ideally this would not have a prefix of '_' since it is
    # a part of the rpc API. However, this is how it was being called when the
    # 1.0 API was being documented using this client proxy class.  It should be
    # changed if there was ever a 2.0.
    def _disassociate_floating_ip(self, ctxt, address, interface, host,
                                  instance_uuid=None):
        cctxt = self.client.prepare(server=host, version='1.6')
        return cctxt.call(ctxt, '_disassociate_floating_ip',
                          address=address, interface=interface,
                          instance_uuid=instance_uuid)

    def lease_fixed_ip(self, ctxt, address, host):
        cctxt = self.client.prepare(server=host)
        cctxt.cast(ctxt, 'lease_fixed_ip', address=address)

    def release_fixed_ip(self, ctxt, address, host, mac):
        kwargs = {}
        if self.client.can_send_version('1.14'):
            version = '1.14'
            kwargs['mac'] = mac
        else:
            version = '1.0'
        cctxt = self.client.prepare(server=host, version=version)
        cctxt.cast(ctxt, 'release_fixed_ip', address=address, **kwargs)

    def migrate_instance_start(self, ctxt, instance_uuid, rxtx_factor,
                               project_id, source_compute, dest_compute,
                               floating_addresses, host=None):
        cctxt = self.client.prepare(server=host, version='1.2')
        return cctxt.call(ctxt, 'migrate_instance_start',
                          instance_uuid=instance_uuid,
                          rxtx_factor=rxtx_factor,
                          project_id=project_id,
                          source=source_compute,
                          dest=dest_compute,
                          floating_addresses=floating_addresses)

    def migrate_instance_finish(self, ctxt, instance_uuid, rxtx_factor,
                                project_id, source_compute, dest_compute,
                                floating_addresses, host=None):
        cctxt = self.client.prepare(server=host, version='1.2')
        return cctxt.call(ctxt, 'migrate_instance_finish',
                          instance_uuid=instance_uuid,
                          rxtx_factor=rxtx_factor,
                          project_id=project_id,
                          source=source_compute,
                          dest=dest_compute,
                          floating_addresses=floating_addresses)
