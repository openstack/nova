# Copyright 2011 OpenStack Foundation
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

import functools

import netaddr
from oslo_serialization import jsonutils
import six

from nova import exception
from nova.i18n import _
from nova import utils


# Constants for the 'vif_type' field in VIF class
VIF_TYPE_OVS = 'ovs'
VIF_TYPE_IVS = 'ivs'
VIF_TYPE_DVS = 'dvs'
VIF_TYPE_IOVISOR = 'iovisor'
VIF_TYPE_BRIDGE = 'bridge'
VIF_TYPE_802_QBG = '802.1qbg'
VIF_TYPE_802_QBH = '802.1qbh'
VIF_TYPE_HW_VEB = 'hw_veb'
VIF_TYPE_HYPERV = 'hyperv'
VIF_TYPE_HOSTDEV = 'hostdev_physical'
VIF_TYPE_IB_HOSTDEV = 'ib_hostdev'
VIF_TYPE_MIDONET = 'midonet'
VIF_TYPE_VHOSTUSER = 'vhostuser'
VIF_TYPE_VROUTER = 'vrouter'
VIF_TYPE_OTHER = 'other'
VIF_TYPE_TAP = 'tap'
VIF_TYPE_MACVTAP = 'macvtap'
VIF_TYPE_AGILIO_OVS = 'agilio_ovs'
VIF_TYPE_BINDING_FAILED = 'binding_failed'
VIF_TYPE_VIF = 'vif'

# Constants for dictionary keys in the 'vif_details' field in the VIF
# class
VIF_DETAILS_PORT_FILTER = 'port_filter'
VIF_DETAILS_OVS_HYBRID_PLUG = 'ovs_hybrid_plug'
VIF_DETAILS_PHYSICAL_NETWORK = 'physical_network'
VIF_DETAILS_BRIDGE_NAME = 'bridge_name'

# The following constant defines an SR-IOV related parameter in the
# 'vif_details'. 'profileid' should be used for VIF_TYPE_802_QBH
VIF_DETAILS_PROFILEID = 'profileid'

# The following constant defines an SR-IOV and macvtap related parameter in
# the 'vif_details'. 'vlan' should be used for VIF_TYPE_HW_VEB or
# VIF_TYPE_MACVTAP
VIF_DETAILS_VLAN = 'vlan'

# The following three constants define the macvtap related fields in
# the 'vif_details'.
VIF_DETAILS_MACVTAP_SOURCE = 'macvtap_source'
VIF_DETAILS_MACVTAP_MODE = 'macvtap_mode'
VIF_DETAILS_PHYS_INTERFACE = 'physical_interface'

# Constants for vhost-user related fields in 'vif_details'.
# Sets mode on vhost-user socket, valid values are 'client'
# and 'server'
VIF_DETAILS_VHOSTUSER_MODE = 'vhostuser_mode'
# vhost-user socket path
VIF_DETAILS_VHOSTUSER_SOCKET = 'vhostuser_socket'
# Specifies whether vhost-user socket should be plugged
# into ovs bridge. Valid values are True and False
VIF_DETAILS_VHOSTUSER_OVS_PLUG = 'vhostuser_ovs_plug'
# Specifies whether vhost-user socket should be used to
# create a fp netdevice interface.
VIF_DETAILS_VHOSTUSER_FP_PLUG = 'vhostuser_fp_plug'
# Specifies whether vhost-user socket should be used to
# create a vrouter netdevice interface
# TODO(mhenkel): Consider renaming this to be contrail-specific.
VIF_DETAILS_VHOSTUSER_VROUTER_PLUG = 'vhostuser_vrouter_plug'
# ovs vhost user interface type name
OVS_VHOSTUSER_INTERFACE_TYPE = 'dpdkvhostuser'

# Constants for dictionary keys in the 'vif_details' field that are
# valid for VIF_TYPE_TAP.
VIF_DETAILS_TAP_MAC_ADDRESS = 'mac_address'

# Define supported virtual NIC types. VNIC_TYPE_DIRECT and VNIC_TYPE_MACVTAP
# are used for SR-IOV ports
VNIC_TYPE_NORMAL = 'normal'
VNIC_TYPE_DIRECT = 'direct'
VNIC_TYPE_MACVTAP = 'macvtap'
VNIC_TYPE_DIRECT_PHYSICAL = 'direct-physical'
VNIC_TYPE_BAREMETAL = 'baremetal'
VNIC_TYPE_VIRTIO_FORWARDER = 'virtio-forwarder'

# Define list of ports which needs pci request.
# Note: The macvtap port needs a PCI request as it is a tap interface
# with VF as the lower physical interface.
# Note: Currently, VNIC_TYPE_VIRTIO_FORWARDER assumes a 1:1
# relationship with a VF. This is expected to change in the future.
VNIC_TYPES_SRIOV = (VNIC_TYPE_DIRECT, VNIC_TYPE_MACVTAP,
                    VNIC_TYPE_DIRECT_PHYSICAL, VNIC_TYPE_VIRTIO_FORWARDER)

# Define list of ports which are passthrough to the guest
# and need a special treatment on snapshot and suspend/resume
VNIC_TYPES_DIRECT_PASSTHROUGH = (VNIC_TYPE_DIRECT,
                                 VNIC_TYPE_DIRECT_PHYSICAL)

# Constants for the 'vif_model' values
VIF_MODEL_VIRTIO = 'virtio'
VIF_MODEL_NE2K_PCI = 'ne2k_pci'
VIF_MODEL_PCNET = 'pcnet'
VIF_MODEL_RTL8139 = 'rtl8139'
VIF_MODEL_E1000 = 'e1000'
VIF_MODEL_E1000E = 'e1000e'
VIF_MODEL_NETFRONT = 'netfront'
VIF_MODEL_SPAPR_VLAN = 'spapr-vlan'
VIF_MODEL_LAN9118 = 'lan9118'

VIF_MODEL_SRIOV = 'sriov'
VIF_MODEL_VMXNET = 'vmxnet'
VIF_MODEL_VMXNET3 = 'vmxnet3'

VIF_MODEL_ALL = (
    VIF_MODEL_VIRTIO,
    VIF_MODEL_NE2K_PCI,
    VIF_MODEL_PCNET,
    VIF_MODEL_RTL8139,
    VIF_MODEL_E1000,
    VIF_MODEL_E1000E,
    VIF_MODEL_NETFRONT,
    VIF_MODEL_SPAPR_VLAN,
    VIF_MODEL_LAN9118,
    VIF_MODEL_SRIOV,
    VIF_MODEL_VMXNET,
    VIF_MODEL_VMXNET3,
)

# these types have been leaked to guests in network_data.json
LEGACY_EXPOSED_VIF_TYPES = (
    VIF_TYPE_BRIDGE,
    VIF_TYPE_DVS,
    VIF_TYPE_HW_VEB,
    VIF_TYPE_HYPERV,
    VIF_TYPE_OVS,
    VIF_TYPE_TAP,
    VIF_TYPE_VHOSTUSER,
    VIF_TYPE_VIF,
)

# Constant for max length of network interface names
# eg 'bridge' in the Network class or 'devname' in
# the VIF class
NIC_NAME_LEN = 14


class Model(dict):
    """Defines some necessary structures for most of the network models."""
    def __repr__(self):
        return jsonutils.dumps(self)

    def _set_meta(self, kwargs):
        # pull meta out of kwargs if it's there
        self['meta'] = kwargs.pop('meta', {})
        # update meta with any additional kwargs that may exist
        self['meta'].update(kwargs)

    def get_meta(self, key, default=None):
        """calls get(key, default) on self['meta']."""
        return self['meta'].get(key, default)


class IP(Model):
    """Represents an IP address in Nova."""
    def __init__(self, address=None, type=None, **kwargs):
        super(IP, self).__init__()

        self['address'] = address
        self['type'] = type
        self['version'] = kwargs.pop('version', None)

        self._set_meta(kwargs)

        # determine version from address if not passed in
        if self['address'] and not self['version']:
            try:
                self['version'] = netaddr.IPAddress(self['address']).version
            except netaddr.AddrFormatError:
                msg = _("Invalid IP format %s") % self['address']
                raise exception.InvalidIpAddressError(msg)

    def __eq__(self, other):
        keys = ['address', 'type', 'version']
        return all(self[k] == other[k] for k in keys)

    def __ne__(self, other):
        return not self.__eq__(other)

    def is_in_subnet(self, subnet):
        if self['address'] and subnet['cidr']:
            return (netaddr.IPAddress(self['address']) in
                    netaddr.IPNetwork(subnet['cidr']))
        else:
            return False

    @classmethod
    def hydrate(cls, ip):
        if ip:
            return cls(**ip)
        return None


class FixedIP(IP):
    """Represents a Fixed IP address in Nova."""
    def __init__(self, floating_ips=None, **kwargs):
        super(FixedIP, self).__init__(**kwargs)
        self['floating_ips'] = floating_ips or []

        if not self['type']:
            self['type'] = 'fixed'

    def add_floating_ip(self, floating_ip):
        if floating_ip not in self['floating_ips']:
            self['floating_ips'].append(floating_ip)

    def floating_ip_addresses(self):
        return [ip['address'] for ip in self['floating_ips']]

    @staticmethod
    def hydrate(fixed_ip):
        fixed_ip = FixedIP(**fixed_ip)
        fixed_ip['floating_ips'] = [IP.hydrate(floating_ip)
                                   for floating_ip in fixed_ip['floating_ips']]
        return fixed_ip

    def __eq__(self, other):
        keys = ['address', 'type', 'version', 'floating_ips']
        return all(self[k] == other[k] for k in keys)

    def __ne__(self, other):
        return not self.__eq__(other)


class Route(Model):
    """Represents an IP Route in Nova."""
    def __init__(self, cidr=None, gateway=None, interface=None, **kwargs):
        super(Route, self).__init__()

        self['cidr'] = cidr
        self['gateway'] = gateway
        # FIXME(mriedem): Is this actually used? It's never set.
        self['interface'] = interface

        self._set_meta(kwargs)

    @classmethod
    def hydrate(cls, route):
        route = cls(**route)
        route['gateway'] = IP.hydrate(route['gateway'])
        return route


class Subnet(Model):
    """Represents a Subnet in Nova."""
    def __init__(self, cidr=None, dns=None, gateway=None, ips=None,
                 routes=None, **kwargs):
        super(Subnet, self).__init__()

        self['cidr'] = cidr
        self['dns'] = dns or []
        self['gateway'] = gateway
        self['ips'] = ips or []
        self['routes'] = routes or []
        self['version'] = kwargs.pop('version', None)

        self._set_meta(kwargs)

        if self['cidr'] and not self['version']:
            self['version'] = netaddr.IPNetwork(self['cidr']).version

    def __eq__(self, other):
        keys = ['cidr', 'dns', 'gateway', 'ips', 'routes', 'version']
        return all(self[k] == other[k] for k in keys)

    def __ne__(self, other):
        return not self.__eq__(other)

    def add_route(self, new_route):
        if new_route not in self['routes']:
            self['routes'].append(new_route)

    def add_dns(self, dns):
        if dns not in self['dns']:
            self['dns'].append(dns)

    def add_ip(self, ip):
        if ip not in self['ips']:
            self['ips'].append(ip)

    def as_netaddr(self):
        """Convenient function to get cidr as a netaddr object."""
        return netaddr.IPNetwork(self['cidr'])

    @classmethod
    def hydrate(cls, subnet):
        subnet = cls(**subnet)
        subnet['dns'] = [IP.hydrate(dns) for dns in subnet['dns']]
        subnet['ips'] = [FixedIP.hydrate(ip) for ip in subnet['ips']]
        subnet['routes'] = [Route.hydrate(route) for route in subnet['routes']]
        subnet['gateway'] = IP.hydrate(subnet['gateway'])
        return subnet


class Network(Model):
    """Represents a Network in Nova."""
    def __init__(self, id=None, bridge=None, label=None,
                 subnets=None, **kwargs):
        super(Network, self).__init__()

        self['id'] = id
        self['bridge'] = bridge
        self['label'] = label
        self['subnets'] = subnets or []

        self._set_meta(kwargs)

    def add_subnet(self, subnet):
        if subnet not in self['subnets']:
            self['subnets'].append(subnet)

    @classmethod
    def hydrate(cls, network):
        if network:
            network = cls(**network)
            network['subnets'] = [Subnet.hydrate(subnet)
                                  for subnet in network['subnets']]
        return network

    def __eq__(self, other):
        keys = ['id', 'bridge', 'label', 'subnets']
        return all(self[k] == other[k] for k in keys)

    def __ne__(self, other):
        return not self.__eq__(other)


class VIF8021QbgParams(Model):
    """Represents the parameters for a 802.1qbg VIF."""

    def __init__(self, managerid, typeid, typeidversion, instanceid):
        super(VIF8021QbgParams, self).__init__()

        self['managerid'] = managerid
        self['typeid'] = typeid
        self['typeidversion'] = typeidversion
        self['instanceid'] = instanceid


class VIF8021QbhParams(Model):
    """Represents the parameters for a 802.1qbh VIF."""

    def __init__(self, profileid):
        super(VIF8021QbhParams, self).__init__()

        self['profileid'] = profileid


class VIF(Model):
    """Represents a Virtual Interface in Nova."""
    def __init__(self, id=None, address=None, network=None, type=None,
                 details=None, devname=None, ovs_interfaceid=None,
                 qbh_params=None, qbg_params=None, active=False,
                 vnic_type=VNIC_TYPE_NORMAL, profile=None,
                 preserve_on_delete=False, **kwargs):
        super(VIF, self).__init__()

        self['id'] = id
        self['address'] = address
        self['network'] = network or None
        self['type'] = type
        self['details'] = details or {}
        self['devname'] = devname

        self['ovs_interfaceid'] = ovs_interfaceid
        self['qbh_params'] = qbh_params
        self['qbg_params'] = qbg_params
        self['active'] = active
        self['vnic_type'] = vnic_type
        self['profile'] = profile
        self['preserve_on_delete'] = preserve_on_delete

        self._set_meta(kwargs)

    def __eq__(self, other):
        keys = ['id', 'address', 'network', 'vnic_type',
                'type', 'profile', 'details', 'devname',
                'ovs_interfaceid', 'qbh_params', 'qbg_params',
                'active', 'preserve_on_delete']
        return all(self[k] == other[k] for k in keys)

    def __ne__(self, other):
        return not self.__eq__(other)

    def fixed_ips(self):
        if self['network']:
            return [fixed_ip for subnet in self['network']['subnets']
                             for fixed_ip in subnet['ips']]
        else:
            return []

    def floating_ips(self):
        return [floating_ip for fixed_ip in self.fixed_ips()
                            for floating_ip in fixed_ip['floating_ips']]

    def labeled_ips(self):
        """Returns the list of all IPs

        The return value looks like this flat structure::

            {'network_label': 'my_network',
             'network_id': 'n8v29837fn234782f08fjxk3ofhb84',
             'ips': [{'address': '123.123.123.123',
                      'version': 4,
                      'type: 'fixed',
                      'meta': {...}},
                     {'address': '124.124.124.124',
                      'version': 4,
                      'type': 'floating',
                      'meta': {...}},
                     {'address': 'fe80::4',
                      'version': 6,
                      'type': 'fixed',
                      'meta': {...}}]
        """
        if self['network']:
            # remove unnecessary fields on fixed_ips
            ips = [IP(**ip) for ip in self.fixed_ips()]
            for ip in ips:
                # remove floating ips from IP, since this is a flat structure
                # of all IPs
                del ip['meta']['floating_ips']
            # add floating ips to list (if any)
            ips.extend(self.floating_ips())
            return {'network_label': self['network']['label'],
                    'network_id': self['network']['id'],
                    'ips': ips}
        return []

    def is_hybrid_plug_enabled(self):
        return self['details'].get(VIF_DETAILS_OVS_HYBRID_PLUG, False)

    def is_neutron_filtering_enabled(self):
        return self['details'].get(VIF_DETAILS_PORT_FILTER, False)

    def get_physical_network(self):
        phy_network = self['network']['meta'].get('physical_network')
        if not phy_network:
            phy_network = self['details'].get(VIF_DETAILS_PHYSICAL_NETWORK)
        return phy_network

    @classmethod
    def hydrate(cls, vif):
        vif = cls(**vif)
        vif['network'] = Network.hydrate(vif['network'])
        return vif


def get_netmask(ip, subnet):
    """Returns the netmask appropriate for injection into a guest."""
    if ip['version'] == 4:
        return str(subnet.as_netaddr().netmask)
    return subnet.as_netaddr()._prefixlen


class NetworkInfo(list):
    """Stores and manipulates network information for a Nova instance."""

    # NetworkInfo is a list of VIFs

    def fixed_ips(self):
        """Returns all fixed_ips without floating_ips attached."""
        return [ip for vif in self for ip in vif.fixed_ips()]

    def floating_ips(self):
        """Returns all floating_ips."""
        return [ip for vif in self for ip in vif.floating_ips()]

    @classmethod
    def hydrate(cls, network_info):
        if isinstance(network_info, six.string_types):
            network_info = jsonutils.loads(network_info)
        return cls([VIF.hydrate(vif) for vif in network_info])

    def wait(self, do_raise=True):
        """Wait for asynchronous call to finish."""
        # There is no asynchronous call for this class, so this is a no-op
        # here, but subclasses may override to provide asynchronous
        # capabilities. Must be defined here in the parent class so that code
        # which works with both parent and subclass types can reference this
        # method.
        pass

    def json(self):
        return jsonutils.dumps(self)


class NetworkInfoAsyncWrapper(NetworkInfo):
    """Wrapper around NetworkInfo that allows retrieving NetworkInfo
    in an async manner.

    This allows one to start querying for network information before
    you know you will need it.  If you have a long-running
    operation, this allows the network model retrieval to occur in the
    background.  When you need the data, it will ensure the async
    operation has completed.

    As an example:

    def allocate_net_info(arg1, arg2)
        return call_neutron_to_allocate(arg1, arg2)

    network_info = NetworkInfoAsyncWrapper(allocate_net_info, arg1, arg2)
    [do a long running operation -- real network_info will be retrieved
    in the background]
    [do something with network_info]
    """

    def __init__(self, async_method, *args, **kwargs):
        super(NetworkInfoAsyncWrapper, self).__init__()

        self._gt = utils.spawn(async_method, *args, **kwargs)
        methods = ['json', 'fixed_ips', 'floating_ips']
        for method in methods:
            fn = getattr(self, method)
            wrapper = functools.partial(self._sync_wrapper, fn)
            functools.update_wrapper(wrapper, fn)
            setattr(self, method, wrapper)

    def _sync_wrapper(self, wrapped, *args, **kwargs):
        """Synchronize the model before running a method."""
        self.wait()
        return wrapped(*args, **kwargs)

    def __getitem__(self, *args, **kwargs):
        fn = super(NetworkInfoAsyncWrapper, self).__getitem__
        return self._sync_wrapper(fn, *args, **kwargs)

    def __iter__(self, *args, **kwargs):
        fn = super(NetworkInfoAsyncWrapper, self).__iter__
        return self._sync_wrapper(fn, *args, **kwargs)

    def __len__(self, *args, **kwargs):
        fn = super(NetworkInfoAsyncWrapper, self).__len__
        return self._sync_wrapper(fn, *args, **kwargs)

    def __str__(self, *args, **kwargs):
        fn = super(NetworkInfoAsyncWrapper, self).__str__
        return self._sync_wrapper(fn, *args, **kwargs)

    def __repr__(self, *args, **kwargs):
        fn = super(NetworkInfoAsyncWrapper, self).__repr__
        return self._sync_wrapper(fn, *args, **kwargs)

    def wait(self, do_raise=True):
        """Wait for asynchronous call to finish."""
        if self._gt is not None:
            try:
                # NOTE(comstud): This looks funky, but this object is
                # subclassed from list.  In other words, 'self' is really
                # just a list with a bunch of extra methods.  So this
                # line just replaces the current list (which should be
                # empty) with the result.
                self[:] = self._gt.wait()
            except Exception:
                if do_raise:
                    raise
            finally:
                self._gt = None
