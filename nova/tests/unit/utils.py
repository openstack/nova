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

from oslo_config import cfg
from six.moves import range

from nova.compute import flavors
import nova.context
import nova.db
from nova import exception
from nova.image import glance
from nova.network import minidns
from nova.network import model as network_model
from nova import objects
import nova.utils

CONF = cfg.CONF
CONF.import_opt('use_ipv6', 'nova.netconf')


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

    try:
        flavor_ref = nova.db.flavor_create(context, test_flavor)
    except (exception.FlavorExists, exception.FlavorIdExists):
        flavor_ref = nova.db.flavor_get_by_name(context, 'kinda.big')
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
        instance = nova.db.instance_create(context, test_instance)
    return instance


def get_test_network_info(count=1):
    ipv6 = CONF.use_ipv6
    fake = 'fake'
    fake_ip = '0.0.0.0'
    fake_vlan = 100
    fake_bridge_interface = 'eth0'

    def current():
        subnet_4 = network_model.Subnet(cidr=fake_ip,
                                        dns=[network_model.IP(fake_ip),
                                             network_model.IP(fake_ip)],
                                        gateway=network_model.IP(fake_ip),
                                        ips=[network_model.IP(fake_ip),
                                             network_model.IP(fake_ip)],
                                        routes=None,
                                        dhcp_server=fake_ip)
        subnet_6 = network_model.Subnet(cidr=fake_ip,
                                        gateway=network_model.IP(fake_ip),
                                        ips=[network_model.IP(fake_ip),
                                             network_model.IP(fake_ip),
                                             network_model.IP(fake_ip)],
                                        routes=None,
                                        version=6)
        subnets = [subnet_4]
        if ipv6:
            subnets.append(subnet_6)
        network = network_model.Network(id=None,
                                        bridge=fake,
                                        label=None,
                                        subnets=subnets,
                                        vlan=fake_vlan,
                                        bridge_interface=fake_bridge_interface,
                                        injected=False)
        vif = network_model.VIF(id='vif-xxx-yyy-zzz',
                                address=fake,
                                network=network,
                                type=network_model.VIF_TYPE_BRIDGE,
                                devname=None,
                                ovs_interfaceid=None)

        return vif

    return network_model.NetworkInfo([current() for x in range(0, count)])


def is_osx():
    return platform.mac_ver()[0] != ''


def is_linux():
    return platform.system() == 'Linux'


def coreutils_readlink_available():
    _out, err = nova.utils.trycmd('readlink', '-nm', '/')
    return err == ''


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
