#    Copyright 2011 OpenStack Foundation
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

import errno
import platform
import socket
import sys

import mock
from six.moves import range

from nova.compute import flavors
import nova.conf
import nova.context
from nova.db import api as db
from nova import exception
from nova.image import glance
from nova.network import minidns
from nova.network import model as network_model
from nova import objects
from nova.objects import base as obj_base
import nova.utils

CONF = nova.conf.CONF


def get_test_admin_context():
    return nova.context.get_admin_context()


def get_test_image_object(context, instance_ref):
    if not context:
        context = get_test_admin_context()

    image_ref = instance_ref['image_ref']
    image_service, image_id = glance.get_remote_image_service(context,
                                                              image_ref)
    return objects.ImageMeta.from_dict(
        image_service.show(context, image_id))


def get_test_flavor(context=None, options=None):
    options = options or {}
    if not context:
        context = get_test_admin_context()

    test_flavor = {'name': 'kinda.big',
                   'flavorid': 'someid',
                   'memory_mb': 2048,
                   'vcpus': 4,
                   'root_gb': 40,
                   'ephemeral_gb': 80,
                   'swap': 1024}

    test_flavor.update(options)
    flavor_ref = objects.Flavor(context, **test_flavor)
    try:
        flavor_ref.create()
    except (exception.FlavorExists, exception.FlavorIdExists):
        flavor_ref = objects.Flavor.get_by_flavor_id(
            context, test_flavor['flavorid'])
    return flavor_ref


def get_test_instance(context=None, flavor=None, obj=False):
    if not context:
        context = get_test_admin_context()

    if not flavor:
        flavor = get_test_flavor(context)

    test_instance = {'memory_kb': '2048000',
                     'basepath': '/some/path',
                     'bridge_name': 'br100',
                     'vcpus': 4,
                     'root_gb': 40,
                     'bridge': 'br101',
                     'image_ref': 'cedef40a-ed67-4d10-800e-17455edce175',
                     'instance_type_id': flavor['id'],
                     'system_metadata': {},
                     'extra_specs': {},
                     'user_id': context.user_id,
                     'project_id': context.project_id,
                     }

    if obj:
        instance = objects.Instance(context, **test_instance)
        instance.flavor = objects.Flavor.get_by_id(context, flavor['id'])
        instance.create()
    else:
        flavors.save_flavor_info(test_instance['system_metadata'], flavor, '')
        instance = db.instance_create(context, test_instance)
    return instance

FAKE_NETWORK_VLAN = 100
FAKE_NETWORK_BRIDGE = 'br0'
FAKE_NETWORK_INTERFACE = 'eth0'

FAKE_NETWORK_IP4_ADDR1 = '10.0.0.73'
FAKE_NETWORK_IP4_ADDR2 = '10.0.0.74'
FAKE_NETWORK_IP6_ADDR1 = '2001:b105:f00d::1'
FAKE_NETWORK_IP6_ADDR2 = '2001:b105:f00d::2'
FAKE_NETWORK_IP6_ADDR3 = '2001:b105:f00d::3'

FAKE_NETWORK_IP4_GATEWAY = '10.0.0.254'
FAKE_NETWORK_IP6_GATEWAY = '2001:b105:f00d::ff'

FAKE_NETWORK_IP4_CIDR = '10.0.0.0/24'
FAKE_NETWORK_IP6_CIDR = '2001:b105:f00d::0/64'

FAKE_NETWORK_DNS_IP4_ADDR1 = '192.168.122.1'
FAKE_NETWORK_DNS_IP4_ADDR2 = '192.168.122.2'
FAKE_NETWORK_DNS_IP6_ADDR1 = '2001:dead:beef::1'
FAKE_NETWORK_DNS_IP6_ADDR2 = '2001:dead:beef::2'

FAKE_NETWORK_DHCP_IP4_ADDR = '192.168.122.253'

FAKE_NETWORK_UUID = '4587c867-a2e6-4356-8c5b-bc077dcb8620'

FAKE_VIF_UUID = '51a9642b-1414-4bd6-9a92-1320ddc55a63'
FAKE_VIF_MAC = 'de:ad:be:ef:ca:fe'


def get_test_network_info(count=1):
    ipv6 = CONF.use_ipv6

    def current():
        subnet_4 = network_model.Subnet(
            cidr=FAKE_NETWORK_IP4_CIDR,
            dns=[network_model.IP(FAKE_NETWORK_DNS_IP4_ADDR1),
                 network_model.IP(FAKE_NETWORK_DNS_IP4_ADDR2)],
            gateway=network_model.IP(FAKE_NETWORK_IP4_GATEWAY),
            ips=[network_model.IP(FAKE_NETWORK_IP4_ADDR1),
                 network_model.IP(FAKE_NETWORK_IP4_ADDR2)],
            routes=None,
            dhcp_server=FAKE_NETWORK_DHCP_IP4_ADDR)
        subnet_6 = network_model.Subnet(
            cidr=FAKE_NETWORK_IP6_CIDR,
            gateway=network_model.IP(FAKE_NETWORK_IP6_GATEWAY),
            ips=[network_model.IP(FAKE_NETWORK_IP6_ADDR1),
                 network_model.IP(FAKE_NETWORK_IP6_ADDR2),
                 network_model.IP(FAKE_NETWORK_IP6_ADDR3)],
            routes=None,
            version=6)
        subnets = [subnet_4]
        if ipv6:
            subnets.append(subnet_6)
        network = network_model.Network(
            id=FAKE_NETWORK_UUID,
            bridge=FAKE_NETWORK_BRIDGE,
            label=None,
            subnets=subnets,
            vlan=FAKE_NETWORK_VLAN,
            bridge_interface=FAKE_NETWORK_INTERFACE,
            injected=False)
        if CONF.use_neutron:
            vif_type = network_model.VIF_TYPE_OVS
        else:
            vif_type = network_model.VIF_TYPE_BRIDGE
        vif = network_model.VIF(
            id=FAKE_VIF_UUID,
            address=FAKE_VIF_MAC,
            network=network,
            type=vif_type,
            devname=None,
            ovs_interfaceid=None)

        return vif

    return network_model.NetworkInfo([current() for x in range(0, count)])


def is_osx():
    return platform.mac_ver()[0] != ''


def is_linux():
    return platform.system() == 'Linux'


test_dns_managers = []


def dns_manager():
    global test_dns_managers
    manager = minidns.MiniDNS()
    test_dns_managers.append(manager)
    return manager


def cleanup_dns_managers():
    global test_dns_managers
    for manager in test_dns_managers:
        manager.delete_dns_file()
    test_dns_managers = []


def killer_xml_body():
    return (("""<!DOCTYPE x [
            <!ENTITY a "%(a)s">
            <!ENTITY b "%(b)s">
            <!ENTITY c "%(c)s">]>
        <foo>
            <bar>
                <v1>%(d)s</v1>
            </bar>
        </foo>""") % {
        'a': 'A' * 10,
        'b': '&a;' * 10,
        'c': '&b;' * 10,
        'd': '&c;' * 9999,
    }).strip()


def is_ipv6_supported():
    has_ipv6_support = socket.has_ipv6
    try:
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        s.close()
    except socket.error as e:
        if e.errno == errno.EAFNOSUPPORT:
            has_ipv6_support = False
        else:
            raise

    # check if there is at least one interface with ipv6
    if has_ipv6_support and sys.platform.startswith('linux'):
        try:
            with open('/proc/net/if_inet6') as f:
                if not f.read():
                    has_ipv6_support = False
        except IOError:
            has_ipv6_support = False

    return has_ipv6_support


def get_api_version(request):
    if request.path[2:3].isdigit():
        return int(request.path[2:3])


def compare_obj_primitive(thing1, thing2):
    if isinstance(thing1, obj_base.NovaObject):
        return thing1.obj_to_primitive() == thing2.obj_to_primitive()
    else:
        return thing1 == thing2


def _compare_args(args1, args2, cmp):
    return all(cmp(*pair) for pair in zip(args1, args2))


def _compare_kwargs(kwargs1, kwargs2, cmp):
    return all(cmp(kwargs1[k], kwargs2[k])
               for k in set(list(kwargs1.keys()) + list(kwargs2.keys())))


def _obj_called_with(the_mock, *args, **kwargs):
    if 'obj_cmp' in kwargs:
        cmp = kwargs.pop('obj_cmp')
    else:
        cmp = compare_obj_primitive

    count = 0
    for call in the_mock.call_args_list:
        if (_compare_args(call[0], args, cmp) and
                _compare_kwargs(call[1], kwargs, cmp)):
            count += 1

    return count


def obj_called_with(the_mock, *args, **kwargs):
    return _obj_called_with(the_mock, *args, **kwargs) != 0


def obj_called_once_with(the_mock, *args, **kwargs):
    return _obj_called_with(the_mock, *args, **kwargs) == 1


class CustomMockCallMatcher(object):
    def __init__(self, comparator):
        self.comparator = comparator

    def __eq__(self, other):
        return self.comparator(other)


def assert_instance_delete_notification_by_uuid(
        mock_notify, expected_instance_uuid, expected_notifier,
        expected_context, expect_targeted_context=False):

    match_by_instance_uuid = CustomMockCallMatcher(
        lambda instance:
        instance.uuid == expected_instance_uuid)

    mock_notify.assert_has_calls([
        mock.call(expected_notifier,
                  expected_context,
                  match_by_instance_uuid,
                  'delete.start'),
        mock.call(expected_notifier,
                  expected_context,
                  match_by_instance_uuid,
                  'delete.end')])

    for call in mock_notify.call_args_list:
        if expect_targeted_context:
            assert call[0][1].db_connection is not None
        else:
            assert call[0][1].db_connection is None
