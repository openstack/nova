# Copyright 2011 Rackspace
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_serialization import jsonutils
from oslo_utils.fixture import uuidsentinel as uuids
from six.moves import range

from nova.compute import api as compute_api
from nova.compute import manager as compute_manager
import nova.conf
import nova.context
from nova.db import api as db
from nova import exception
from nova.network import manager as network_manager
from nova.network import model as network_model
from nova.network import rpcapi as network_rpcapi
from nova import objects
from nova.objects import base as obj_base
from nova.objects import network as network_obj
from nova.objects import virtual_interface as vif_obj
from nova.tests.unit.objects import test_fixed_ip
from nova.tests.unit.objects import test_instance_info_cache
from nova.tests.unit.objects import test_pci_device
from nova.tests.unit import utils


HOST = "testhost"
CONF = nova.conf.CONF


class FakeModel(dict):
    """Represent a model from the db."""
    def __init__(self, *args, **kwargs):
        self.update(kwargs)


class FakeNetworkManager(network_manager.NetworkManager):
    """This NetworkManager doesn't call the base class so we can bypass all
    inherited service cruft and just perform unit tests.
    """

    class FakeDB(object):
        vifs = [{'id': 0,
                 'created_at': None,
                 'updated_at': None,
                 'deleted_at': None,
                 'deleted': 0,
                 'instance_uuid': uuids.instance_1,
                 'network_id': 1,
                 'uuid': uuids.vifs_1,
                 'address': 'DC:AD:BE:FF:EF:01',
                 'tag': 'fake-tag1'},
                {'id': 1,
                 'created_at': None,
                 'updated_at': None,
                 'deleted_at': None,
                 'deleted': 0,
                 'instance_uuid': uuids.instance_2,
                 'network_id': 21,
                 'uuid': uuids.vifs_2,
                 'address': 'DC:AD:BE:FF:EF:02',
                 'tag': 'fake-tag2'},
                {'id': 2,
                 'created_at': None,
                 'updated_at': None,
                 'deleted_at': None,
                 'deleted': 0,
                 'instance_uuid': uuids.instance_1,
                 'network_id': 31,
                 'uuid': uuids.vifs_3,
                 'address': 'DC:AD:BE:FF:EF:03',
                 'tag': None}]

        floating_ips = [dict(address='172.16.1.1',
                             fixed_ip_id=100),
                        dict(address='172.16.1.2',
                             fixed_ip_id=200),
                        dict(address='173.16.1.2',
                             fixed_ip_id=210)]

        fixed_ips = [dict(test_fixed_ip.fake_fixed_ip,
                          id=100,
                          address='172.16.0.1',
                          virtual_interface_id=0),
                     dict(test_fixed_ip.fake_fixed_ip,
                          id=200,
                          address='172.16.0.2',
                          virtual_interface_id=1),
                     dict(test_fixed_ip.fake_fixed_ip,
                          id=210,
                          address='173.16.0.2',
                          virtual_interface_id=2)]

        def fixed_ip_get_by_instance(self, context, instance_uuid):
            return [dict(address='10.0.0.0'), dict(address='10.0.0.1'),
                    dict(address='10.0.0.2')]

        def network_get_by_cidr(self, context, cidr):
            raise exception.NetworkNotFoundForCidr(cidr=cidr)

        def network_create_safe(self, context, net):
            fakenet = dict(net)
            fakenet['id'] = 999
            return fakenet

        def network_get(self, context, network_id, project_only="allow_none"):
            return {'cidr_v6': '2001:db8:69:%x::/64' % network_id}

        def network_get_by_uuid(self, context, network_uuid):
            raise exception.NetworkNotFoundForUUID(uuid=network_uuid)

        def network_get_all(self, context):
            raise exception.NoNetworksFound()

        def network_get_all_by_uuids(self, context, project_only="allow_none"):
            raise exception.NoNetworksFound()

        def network_disassociate(self, context, network_id):
            return True

        def virtual_interface_get_all(self, context):
            return self.vifs

        def fixed_ips_by_virtual_interface(self, context, vif_id):
            return [ip for ip in self.fixed_ips
                    if ip['virtual_interface_id'] == vif_id]

        def fixed_ip_disassociate(self, context, address):
            return True

    def __init__(self, stubs=None):
        self.db = self.FakeDB()
        if stubs:
            stubs.Set(vif_obj, 'db', self.db)
        self.deallocate_called = None
        self.deallocate_fixed_ip_calls = []
        self.network_rpcapi = network_rpcapi.NetworkAPI()

    # TODO(matelakat) method signature should align with the faked one's
    def deallocate_fixed_ip(self, context, address=None, host=None,
            instance=None):
        self.deallocate_fixed_ip_calls.append((context, address, host))
        # TODO(matelakat) use the deallocate_fixed_ip_calls instead
        self.deallocate_called = address

    def _create_fixed_ips(self, context, network_id, fixed_cidr=None,
                          extra_reserved=None, bottom_reserved=0,
                          top_reserved=0):
        pass

    def get_instance_nw_info(context, instance_id, rxtx_factor,
                             host, instance_uuid=None, **kwargs):
        pass


def fake_network(network_id, ipv6=None):
    if ipv6 is None:
        ipv6 = CONF.use_ipv6
    fake_network = {'id': network_id,
             'uuid': getattr(uuids, 'network%i' % network_id),
             'label': 'test%d' % network_id,
             'injected': False,
             'multi_host': False,
             'cidr': '192.168.%d.0/24' % network_id,
             'cidr_v6': None,
             'netmask': '255.255.255.0',
             'netmask_v6': None,
             'bridge': 'fake_br%d' % network_id,
             'bridge_interface': 'fake_eth%d' % network_id,
             'gateway': '192.168.%d.1' % network_id,
             'gateway_v6': None,
             'broadcast': '192.168.%d.255' % network_id,
             'dns1': '192.168.%d.3' % network_id,
             'dns2': '192.168.%d.4' % network_id,
             'dns3': '192.168.%d.3' % network_id,
             'vlan': None,
             'host': None,
             'project_id': uuids.project,
             'vpn_public_address': '192.168.%d.2' % network_id,
             'vpn_public_port': None,
             'vpn_private_address': None,
             'dhcp_start': None,
             'rxtx_base': network_id * 10,
             'priority': None,
             'deleted': False,
             'created_at': None,
             'updated_at': None,
             'deleted_at': None,
             'mtu': None,
             'dhcp_server': '192.168.%d.1' % network_id,
             'enable_dhcp': True,
             'share_address': False}
    if ipv6:
        fake_network['cidr_v6'] = '2001:db8:0:%x::/64' % network_id
        fake_network['gateway_v6'] = '2001:db8:0:%x::1' % network_id
        fake_network['netmask_v6'] = '64'
    if CONF.flat_injected:
        fake_network['injected'] = True

    return fake_network


def fake_network_obj(context, network_id=1, ipv6=None):
    return network_obj.Network._from_db_object(
        context, network_obj.Network(), fake_network(network_id, ipv6))


def fake_vif(x):
    return {'id': x,
            'created_at': None,
            'updated_at': None,
            'deleted_at': None,
            'deleted': 0,
            'address': 'DE:AD:BE:EF:00:%02x' % x,
            'uuid': getattr(uuids, 'vif%i' % x),
            'network_id': x,
            'instance_uuid': uuids.vifs_1,
            'tag': 'fake-tag'}


def floating_ip_ids():
    for i in range(1, 100):
        yield i


def fixed_ip_ids():
    for i in range(1, 100):
        yield i


floating_ip_id = floating_ip_ids()
fixed_ip_id = fixed_ip_ids()


def next_fixed_ip(network_id, num_floating_ips=0):
    next_id = next(fixed_ip_id)
    f_ips = [FakeModel(**next_floating_ip(next_id))
             for i in range(num_floating_ips)]
    return {'id': next_id,
            'network_id': network_id,
            'address': '192.168.%d.%03d' % (network_id, (next_id + 99)),
            'instance_uuid': uuids.fixed_ip,
            'allocated': False,
            'reserved': False,
            'created_at': None,
            'updated_at': None,
            'deleted_at': None,
            'leased': True,
            'host': HOST,
            'deleted': 0,
            'network': fake_network(network_id),
            'virtual_interface': fake_vif(network_id),
            # and since network_id and vif_id happen to be equivalent
            'virtual_interface_id': network_id,
            'floating_ips': f_ips}


def next_floating_ip(fixed_ip_id):
    next_id = next(floating_ip_id)
    return {'id': next_id,
            'address': '10.10.10.%03d' % (next_id + 99),
            'fixed_ip_id': fixed_ip_id,
            'project_id': None,
            'auto_assigned': False}


def ipv4_like(ip, match_string):
    ip = ip.split('.')
    match_octets = match_string.split('.')

    for i, octet in enumerate(match_octets):
        if octet == '*':
            continue
        if octet != ip[i]:
            return False
    return True


def fake_get_instance_nw_info(test, num_networks=1, ips_per_vif=2,
                              floating_ips_per_fixed_ip=0):
    # test is an instance of nova.test.TestCase
    # ips_per_vif is the number of ips each vif will have
    # num_floating_ips is number of float ips for each fixed ip
    network = network_manager.FlatManager(host=HOST)
    network.db = db

    # reset the fixed and floating ip generators
    global floating_ip_id, fixed_ip_id, fixed_ips
    floating_ip_id = floating_ip_ids()
    fixed_ip_id = fixed_ip_ids()
    fixed_ips = []

    def fixed_ips_fake(*args, **kwargs):
        global fixed_ips
        ips = [next_fixed_ip(i, floating_ips_per_fixed_ip)
               for i in range(1, num_networks + 1)
               for j in range(ips_per_vif)]
        fixed_ips = ips
        return ips

    def update_cache_fake(*args, **kwargs):
        fake_info_cache = {
            'created_at': None,
            'updated_at': None,
            'deleted_at': None,
            'deleted': False,
            'instance_uuid': uuids.vifs_1,
            'network_info': '[]',
            }
        return fake_info_cache

    test.stub_out('nova.db.api.fixed_ip_get_by_instance', fixed_ips_fake)
    test.stub_out('nova.db.api.instance_info_cache_update', update_cache_fake)

    class FakeContext(nova.context.RequestContext):
        def is_admin(self):
            return True

    nw_model = network.get_instance_nw_info(
                FakeContext('fakeuser', 'fake_project'),
                0, 3, None)
    return nw_model


def stub_out_nw_api_get_instance_nw_info(test, func=None,
                                         num_networks=1,
                                         ips_per_vif=1,
                                         floating_ips_per_fixed_ip=0):

    def get_instance_nw_info(self, context, instance, conductor_api=None):
        return fake_get_instance_nw_info(test, num_networks=num_networks,
                        ips_per_vif=ips_per_vif,
                        floating_ips_per_fixed_ip=floating_ips_per_fixed_ip)

    if func is None:
        func = get_instance_nw_info
    test.stub_out('nova.network.api.API.get_instance_nw_info', func)


_real_functions = {}


def set_stub_network_methods(test):
    global _real_functions
    cm = compute_manager.ComputeManager
    if not _real_functions:
        _real_functions = {
                '_allocate_network': cm._allocate_network,
                '_deallocate_network': cm._deallocate_network}

    def fake_networkinfo(*args, **kwargs):
        return network_model.NetworkInfo()

    def fake_async_networkinfo(*args, **kwargs):
        return network_model.NetworkInfoAsyncWrapper(fake_networkinfo)

    test.stub_out('nova.compute.manager.ComputeManager._allocate_network',
                  fake_async_networkinfo)
    test.stub_out('nova.compute.manager.ComputeManager._deallocate_network',
                  lambda *args, **kwargs: None)


def unset_stub_network_methods(test):
    global _real_functions
    if _real_functions:
        for name in _real_functions:
            test.stub_out('nova.compute.manager.ComputeManager.' + name,
                          _real_functions[name])


def stub_compute_with_ips(test):
    orig_get = compute_api.API.get
    orig_get_all = compute_api.API.get_all
    orig_create = compute_api.API.create

    def fake_get(*args, **kwargs):
        return _get_instances_with_cached_ips(orig_get, *args, **kwargs)

    def fake_get_all(*args, **kwargs):
        return _get_instances_with_cached_ips(orig_get_all, *args, **kwargs)

    def fake_create(*args, **kwargs):
        return _create_instances_with_cached_ips(orig_create, *args, **kwargs)

    def fake_pci_device_get_by_addr(context, node_id, dev_addr):
        return test_pci_device.fake_db_dev

    test.stub_out('nova.db.api.pci_device_get_by_addr',
                  fake_pci_device_get_by_addr)
    test.stub_out('nova.compute.api.API.get', fake_get)
    test.stub_out('nova.compute.api.API.get_all', fake_get_all)
    test.stub_out('nova.compute.api.API.create', fake_create)


def _get_fake_cache():
    def _ip(ip, fixed=True, floats=None):
        ip_dict = {'address': ip, 'type': 'fixed'}
        if not fixed:
            ip_dict['type'] = 'floating'
        if fixed and floats:
            ip_dict['floating_ips'] = [_ip(f, fixed=False) for f in floats]
        return ip_dict

    info = [{'address': 'aa:bb:cc:dd:ee:ff',
             'id': utils.FAKE_NETWORK_UUID,
             'network': {'bridge': 'br0',
                         'id': 1,
                         'label': 'private',
                         'subnets': [{'cidr': '192.168.0.0/24',
                                      'ips': [_ip('192.168.0.3')]}]}}]
    if CONF.use_ipv6:
        ipv6_addr = 'fe80:b33f::a8bb:ccff:fedd:eeff'
        info[0]['network']['subnets'].append({'cidr': 'fe80:b33f::/64',
                                              'ips': [_ip(ipv6_addr)]})
    return jsonutils.dumps(info)


def _get_instances_with_cached_ips(orig_func, *args, **kwargs):
    """Kludge the cache into instance(s) without having to create DB
    entries
    """
    instances = orig_func(*args, **kwargs)
    context = args[0]
    fake_device = objects.PciDevice.get_by_dev_addr(context, 1, 'a')

    def _info_cache_for(instance):
        info_cache = dict(test_instance_info_cache.fake_info_cache,
                          network_info=_get_fake_cache(),
                          instance_uuid=instance['uuid'])
        if isinstance(instance, obj_base.NovaObject):
            _info_cache = objects.InstanceInfoCache(context)
            objects.InstanceInfoCache._from_db_object(context, _info_cache,
                                                      info_cache)
            info_cache = _info_cache
        instance['info_cache'] = info_cache

    if isinstance(instances, (list, obj_base.ObjectListBase)):
        for instance in instances:
            _info_cache_for(instance)
            fake_device.claim(instance.uuid)
            fake_device.allocate(instance)
    else:
        _info_cache_for(instances)
        fake_device.claim(instances.uuid)
        fake_device.allocate(instances)
    return instances


def _create_instances_with_cached_ips(orig_func, *args, **kwargs):
    """Kludge the above kludge so that the database doesn't get out
    of sync with the actual instance.
    """
    instances, reservation_id = orig_func(*args, **kwargs)
    fake_cache = _get_fake_cache()
    for instance in instances:
        instance['info_cache'].network_info = fake_cache
        db.instance_info_cache_update(args[1], instance['uuid'],
                                      {'network_info': fake_cache})
    return (instances, reservation_id)
