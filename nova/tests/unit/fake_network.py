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

from nova.compute import manager as compute_manager
from nova.db import api as db
from nova.network import model as network_model
from nova import objects
from nova.objects import base as obj_base
from nova.tests.unit.objects import test_instance_info_cache
from nova.tests.unit import utils


def fake_get_instance_nw_info(test, num_networks=1):

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

    test.stub_out('nova.db.api.instance_info_cache_update', update_cache_fake)

    # TODO(stephenfin): This doesn't match the kind of object we would receive
    # from '_build_vif_model' and callers of same. We should fix that.
    nw_model = network_model.NetworkInfo()
    for network_id in range(1, num_networks + 1):
        network = network_model.Network(
            id=getattr(uuids, 'network%i' % network_id),
            bridge='fake_br%d' % network_id,
            label='test%d' % network_id,
            subnets=[
                network_model.Subnet(
                    cidr='192.168.%d.0/24' % network_id,
                    dns=[
                        network_model.IP(
                            address='192.168.%d.3' % network_id,
                            type='dns',
                            version=4,
                            meta={},
                        ),
                        network_model.IP(
                            address='192.168.%d.4' % network_id,
                            type='dns',
                            version=4,
                            meta={},
                        ),
                    ],
                    gateway=network_model.IP(
                        address='192.168.%d.1' % network_id,
                        type='gateway',
                        version=4,
                        meta={},
                    ),
                    ips=[
                        network_model.FixedIP(
                            address='192.168.%d.100' % network_id,
                            version=4,
                            meta={},
                        ),
                    ],
                    routes=[],
                    version=4,
                    meta={},
                ),
                network_model.Subnet(
                    cidr='2001:db8:0:%x::/64' % network_id,
                    dns=[],
                    gateway=network_model.IP(
                        address='2001:db8:0:%x::1' % network_id,
                        type='gateway',
                        version=6,
                        meta={},
                    ),
                    ips=[
                        network_model.FixedIP(
                            address='2001:db8:0:%x:dcad:beff:feef:1' % (
                                network_id),
                            version=6,
                            meta={},
                        ),
                    ],
                    routes=[],
                    version=6,
                    meta={}
                ),
            ],
            meta={
                "tenant_id": "806e1f03-b36f-4fc6-be29-11a366f150eb"
            },
        )
        vif = network_model.VIF(
            id=getattr(uuids, 'vif%i' % network_id),
            address='DE:AD:BE:EF:00:%02x' % network_id,
            network=network,
            type='bridge',
            details={},
            devname=None,
            ovs_interfaceid=None,
            qbh_params=None,
            qbg_params=None,
            active=False,
            vnic_type='normal',
            profile=None,
            preserve_on_delete=False,
            meta={'rxtx_cap': 30},
        )
        nw_model.append(vif)

    return nw_model


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
    return instances, reservation_id
