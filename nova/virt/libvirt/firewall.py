# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
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


from eventlet import tpool

from nova import context
from nova import db
from nova import flags
from nova import log as logging
from nova import utils

import nova.virt.firewall as base_firewall
from nova.virt import netutils


LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS

# The default Firewall driver must be listed at position 0
drivers = ['nova.virt.libvirt.firewall.IptablesFirewallDriver', ]

try:
    import libvirt
except ImportError:
    LOG.warn(_("Libvirt module could not be loaded. NWFilterFirewall will "
               "not work correctly."))


class NWFilterFirewall(base_firewall.FirewallDriver):
    """
    This class implements a network filtering mechanism by using
    libvirt's nwfilter.
    all instances get a filter ("nova-base") applied. This filter
    provides some basic security such as protection against MAC
    spoofing, IP spoofing, and ARP spoofing.
    """

    def __init__(self, get_connection, **kwargs):
        self._libvirt_get_connection = get_connection
        self.static_filters_configured = False
        self.handle_security_groups = False

    def apply_instance_filter(self, instance, network_info):
        """No-op. Everything is done in prepare_instance_filter"""
        pass

    def _get_connection(self):
        return self._libvirt_get_connection()
    _conn = property(_get_connection)

    @staticmethod
    def nova_dhcp_filter():
        """The standard allow-dhcp-server filter is an <ip> one, so it uses
           ebtables to allow traffic through. Without a corresponding rule in
           iptables, it'll get blocked anyway."""

        return '''<filter name='nova-allow-dhcp-server' chain='ipv4'>
                    <uuid>891e4787-e5c0-d59b-cbd6-41bc3c6b36fc</uuid>
                    <rule action='accept' direction='out'
                          priority='100'>
                      <udp srcipaddr='0.0.0.0'
                           dstipaddr='255.255.255.255'
                           srcportstart='68'
                           dstportstart='67'/>
                    </rule>
                    <rule action='accept' direction='in'
                          priority='100'>
                      <udp srcipaddr='$DHCPSERVER'
                           srcportstart='67'
                           dstportstart='68'/>
                    </rule>
                  </filter>'''

    def setup_basic_filtering(self, instance, network_info):
        """Set up basic filtering (MAC, IP, and ARP spoofing protection)"""
        LOG.info(_('Called setup_basic_filtering in nwfilter'),
                 instance=instance)

        if self.handle_security_groups:
            # No point in setting up a filter set that we'll be overriding
            # anyway.
            return

        LOG.info(_('Ensuring static filters'), instance=instance)
        self._ensure_static_filters()

        if instance['image_ref'] == str(FLAGS.vpn_image_id):
            base_filter = 'nova-vpn'
        else:
            base_filter = 'nova-base'

        for (network, mapping) in network_info:
            nic_id = mapping['mac'].replace(':', '')
            instance_filter_name = self._instance_filter_name(instance, nic_id)
            self._define_filter(self._filter_container(instance_filter_name,
                                                       [base_filter]))

    def _ensure_static_filters(self):
        """Static filters are filters that have no need to be IP aware.

        There is no configuration or tuneability of these filters, so they
        can be set up once and forgotten about.

        """

        if self.static_filters_configured:
            return

        self._define_filter(self._filter_container('nova-base',
                                                   ['no-mac-spoofing',
                                                    'no-ip-spoofing',
                                                    'no-arp-spoofing',
                                                    'allow-dhcp-server']))
        self._define_filter(self._filter_container('nova-vpn',
                                                   ['allow-dhcp-server']))
        self._define_filter(self.nova_dhcp_filter)

        self.static_filters_configured = True

    def _filter_container(self, name, filters):
        xml = '''<filter name='%s' chain='root'>%s</filter>''' % (
                 name,
                 ''.join(["<filterref filter='%s'/>" % (f,) for f in filters]))
        return xml

    def _define_filter(self, xml):
        if callable(xml):
            xml = xml()
        # execute in a native thread and block current greenthread until done
        tpool.execute(self._conn.nwfilterDefineXML, xml)

    def unfilter_instance(self, instance, network_info):
        """Clear out the nwfilter rules."""
        instance_name = instance.name
        for (network, mapping) in network_info:
            nic_id = mapping['mac'].replace(':', '')
            instance_filter_name = self._instance_filter_name(instance, nic_id)

            try:
                _nw = self._conn.nwfilterLookupByName(instance_filter_name)
                _nw.undefine()
            except libvirt.libvirtError:
                LOG.debug(_('The nwfilter(%(instance_filter_name)s) '
                            'is not found.') % locals(),
                          instance=instance)

    def _create_network_filters(self, instance, network_info,
                               instance_secgroup_filter_name):
        if instance['image_ref'] == str(FLAGS.vpn_image_id):
            base_filter = 'nova-vpn'
        else:
            base_filter = 'nova-base'

        result = []
        for (_n, mapping) in network_info:
            nic_id = mapping['mac'].replace(':', '')
            instance_filter_name = self._instance_filter_name(instance, nic_id)
            instance_filter_children = [base_filter, 'nova-provider-rules',
                                        instance_secgroup_filter_name]

            if FLAGS.allow_same_net_traffic:
                instance_filter_children.append('nova-project')
                if FLAGS.use_ipv6:
                    instance_filter_children.append('nova-project-v6')

            result.append((instance_filter_name, instance_filter_children))

        return result

    def _define_filters(self, filter_name, filter_children):
        self._define_filter(self._filter_container(filter_name,
                                                   filter_children))

    @staticmethod
    def _instance_filter_name(instance, nic_id=None):
        if not nic_id:
            return 'nova-instance-%s' % (instance['name'])
        return 'nova-instance-%s-%s' % (instance['name'], nic_id)

    def instance_filter_exists(self, instance, network_info):
        """Check nova-instance-instance-xxx exists"""
        for (network, mapping) in network_info:
            nic_id = mapping['mac'].replace(':', '')
            instance_filter_name = self._instance_filter_name(instance, nic_id)
            try:
                self._conn.nwfilterLookupByName(instance_filter_name)
            except libvirt.libvirtError:
                name = instance.name
                LOG.debug(_('The nwfilter(%(instance_filter_name)s) for'
                            '%(name)s is not found.') % locals(),
                          instance=instance)
                return False
        return True


class IptablesFirewallDriver(base_firewall.IptablesFirewallDriver):
    def __init__(self, execute=None, **kwargs):
        super(IptablesFirewallDriver, self).__init__(**kwargs)
        self.nwfilter = NWFilterFirewall(kwargs['get_connection'])

    def setup_basic_filtering(self, instance, network_info):
        """Set up provider rules and basic NWFilter."""
        self.nwfilter.setup_basic_filtering(instance, network_info)
        if not self.basicly_filtered:
            LOG.debug(_('iptables firewall: Setup Basic Filtering'),
                      instance=instance)
            self.refresh_provider_fw_rules()
            self.basicly_filtered = True

    def apply_instance_filter(self, instance, network_info):
        """No-op. Everything is done in prepare_instance_filter"""
        pass

    def unfilter_instance(self, instance, network_info):
        # NOTE(salvatore-orlando):
        # Overriding base class method for applying nwfilter operation
        if self.instances.pop(instance['id'], None):
            # NOTE(vish): use the passed info instead of the stored info
            self.network_infos.pop(instance['id'])
            self.remove_filters_for_instance(instance)
            self.iptables.apply()
            self.nwfilter.unfilter_instance(instance, network_info)
        else:
            LOG.info(_('Attempted to unfilter instance which is not '
                     'filtered'), instance=instance)

    def instance_filter_exists(self, instance, network_info):
        """Check nova-instance-instance-xxx exists"""
        return self.nwfilter.instance_filter_exists(instance, network_info)
