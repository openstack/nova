# Copyright 2014 Red Hat, Inc.
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

from nova import objects
from nova.virt.ironic import client_wrapper
from nova.virt.ironic import ironic_states


def get_test_validation(**kw):
    return type('interfaces', (object,),
               {'power': kw.get('power', {'result': True}),
                'deploy': kw.get('deploy', {'result': True}),
                'console': kw.get('console', True),
                'rescue': kw.get('rescue', True),
                'storage': kw.get('storage', {'result': True})})()


def get_test_node(fields=None, **kw):
    # TODO(dustinc): Once the usages of id/uuid, maintenance/is_maintenance,
    #  and portgroup/port_group are normalized, the duplicates can be removed
    _id = kw.get('id') or kw.get('uuid',
                                 'eeeeeeee-dddd-cccc-bbbb-aaaaaaaaaaaa')
    _instance_id = kw.get('instance_id') or kw.get('instance_uuid')
    _is_maintenance = kw.get('is_maintenance') or kw.get('maintenance', False)
    node = {'uuid': _id,
            'id': _id,
            'chassis_uuid': kw.get('chassis_uuid'),
            'power_state': kw.get('power_state',
                                  ironic_states.NOSTATE),
            'target_power_state': kw.get('target_power_state',
                                         ironic_states.NOSTATE),
            'provision_state': kw.get('provision_state',
                                      ironic_states.NOSTATE),
            'target_provision_state': kw.get('target_provision_state',
                                             ironic_states.NOSTATE),
            'last_error': kw.get('last_error'),
            'instance_uuid': _instance_id,
            'instance_id': _instance_id,
            'instance_info': kw.get('instance_info'),
            'driver': kw.get('driver', 'fake'),
            'driver_info': kw.get('driver_info', {}),
            'properties': kw.get('properties', {}),
            'reservation': kw.get('reservation'),
            'maintenance': _is_maintenance,
            'is_maintenance': _is_maintenance,
            'network_interface': kw.get('network_interface'),
            'resource_class': kw.get('resource_class'),
            'traits': kw.get('traits', []),
            'extra': kw.get('extra', {}),
            'updated_at': kw.get('created_at'),
            'created_at': kw.get('updated_at')}
    if fields is not None:
        node = {key: value for key, value in node.items() if key in fields}
    return type('node', (object,), node)()


def get_test_port(**kw):
    # TODO(dustinc): Once the usages of id/uuid, maintenance/is_maintenance,
    #  and portgroup/port_group are normalized, the duplicates can be removed
    _id = kw.get('id') or kw.get('uuid',
                                 'gggggggg-uuuu-qqqq-ffff-llllllllllll')
    _node_id = kw.get('node_uuid') or kw.get('node_id', get_test_node().id)
    _port_group_id = kw.get('port_group_id') or kw.get('portgroup_uuid')
    return type('port', (object,),
               {'uuid': _id,
                'id': _id,
                'node_uuid': _node_id,
                'node_id': _node_id,
                'address': kw.get('address', 'FF:FF:FF:FF:FF:FF'),
                'extra': kw.get('extra', {}),
                'internal_info': kw.get('internal_info', {}),
                'portgroup_uuid': _port_group_id,
                'port_group_id': _port_group_id,
                'created_at': kw.get('created_at'),
                'updated_at': kw.get('updated_at')})()


def get_test_portgroup(**kw):
    # TODO(dustinc): Once the usages of id/uuid, maintenance/is_maintenance,
    #  and portgroup/port_group are normalized, the duplicates can be removed
    _id = kw.get('id') or kw.get('uuid',
                                 'deaffeed-1234-5678-9012-fedcbafedcba')
    _node_id = kw.get('node_id') or kw.get('node_uuid', get_test_node().id)
    return type('portgroup', (object,),
               {'uuid': _id,
                'id': _id,
                'node_uuid': _node_id,
                'node_id': _node_id,
                'address': kw.get('address', 'EE:EE:EE:EE:EE:EE'),
                'extra': kw.get('extra', {}),
                'internal_info': kw.get('internal_info', {}),
                'properties': kw.get('properties', {}),
                'mode': kw.get('mode', 'active-backup'),
                'name': kw.get('name'),
                'standalone_ports_supported': kw.get(
                    'standalone_ports_supported', True),
                'created_at': kw.get('created_at'),
                'updated_at': kw.get('updated_at')})()


def get_test_vif(**kw):
    return {
        'profile': kw.get('profile', {}),
        'ovs_interfaceid': kw.get('ovs_interfaceid'),
        'preserve_on_delete': kw.get('preserve_on_delete', False),
        'network': kw.get('network', {}),
        'devname': kw.get('devname', 'tapaaaaaaaa-00'),
        'vnic_type': kw.get('vnic_type', 'baremetal'),
        'qbh_params': kw.get('qbh_params'),
        'meta': kw.get('meta', {}),
        'details': kw.get('details', {}),
        'address': kw.get('address', 'FF:FF:FF:FF:FF:FF'),
        'active': kw.get('active', True),
        'type': kw.get('type', 'ironic'),
        'id': kw.get('id', 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'),
        'qbg_params': kw.get('qbg_params')}


def get_test_volume_connector(**kw):
    # TODO(dustinc): Once the usages of id/uuid, maintenance/is_maintenance,
    #  and portgroup/port_group are normalized, the duplicates can be removed
    _id = kw.get('id') or kw.get('uuid',
                                 'hhhhhhhh-qqqq-uuuu-mmmm-bbbbbbbbbbbb')
    _node_id = kw.get('node_id') or kw.get('node_uuid', get_test_node().id)
    return type('volume_connector', (object,),
               {'uuid': _id,
                'id': _id,
                'node_uuid': _node_id,
                'node_id': _node_id,
                'type': kw.get('type', 'iqn'),
                'connector_id': kw.get('connector_id', 'iqn.test'),
                'extra': kw.get('extra', {}),
                'created_at': kw.get('created_at'),
                'updated_at': kw.get('updated_at')})()


def get_test_volume_target(**kw):
    # TODO(dustinc): Once the usages of id/uuid, maintenance/is_maintenance,
    #  and portgroup/port_group are normalized, the duplicates can be removed
    _id = kw.get('id') or kw.get('uuid',
                                 'aaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee')
    _node_id = kw.get('node_id') or kw.get('node_uuid', get_test_node().id)
    return type('volume_target', (object,),
                {'uuid': _id,
                 'id': _id,
                 'node_uuid': _node_id,
                 'node_id': _node_id,
                 'volume_type': kw.get('volume_type', 'iscsi'),
                 'properties': kw.get('properties', {}),
                 'boot_index': kw.get('boot_index', 0),
                 'volume_id': kw.get('volume_id',
                                     'fffffff-gggg-hhhh-iiii-jjjjjjjjjjjj'),
                 'extra': kw.get('extra', {}),
                 'created_at': kw.get('created_at'),
                 'updated_at': kw.get('updated_at')})()


def get_test_flavor(**kw):
    default_extra_specs = {'baremetal:deploy_kernel_id':
                                       'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                           'baremetal:deploy_ramdisk_id':
                                       'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'}
    flavor = {'name': kw.get('name', 'fake.flavor'),
              'extra_specs': kw.get('extra_specs', default_extra_specs),
              'swap': kw.get('swap', 0),
              'root_gb': 1,
              'memory_mb': 1,
              'vcpus': 1,
              'ephemeral_gb': kw.get('ephemeral_gb', 0)}
    return objects.Flavor(**flavor)


def get_test_image_meta(**kw):
    return objects.ImageMeta.from_dict(
        {'id': kw.get('id', 'cccccccc-cccc-cccc-cccc-cccccccccccc')})


class FakeVolumeTargetClient(object):

    def create(self, node_uuid, volume_type, properties, boot_index,
               volume_id):
        pass

    def delete(self, volume_target_id):
        pass


class FakePortClient(object):

    def list(self, address=None, limit=None, marker=None, sort_key=None,
             sort_dir=None, detail=False, fields=None, node=None,
             portgroup=None):
        pass

    def get(self, port_uuid):
        pass

    def update(self, port_uuid, patch):
        pass


class FakePortgroupClient(object):

    def list(self, node=None, address=None, limit=None, marker=None,
             sort_key=None, sort_dir=None, detail=False, fields=None):
        pass


class FakeNodeClient(object):

    def list(self, associated=None, maintenance=None, marker=None, limit=None,
             detail=False, sort_key=None, sort_dir=None, fields=None,
             provision_state=None, driver=None, resource_class=None,
             chassis=None):
        return []

    def get(self, node_uuid, fields=None):
        pass

    def get_by_instance_uuid(self, instance_uuid, fields=None):
        pass

    def list_ports(self, node_uuid, detail=False):
        pass

    def set_power_state(self, node_uuid, target, soft=False, timeout=None):
        pass

    def set_provision_state(self, node_uuid, state, configdrive=None,
                            cleansteps=None, rescue_password=None,
                            os_ironic_api_version=None):
        pass

    def update(self, node_uuid, patch):
        pass

    def validate(self, node_uuid):
        pass

    def vif_attach(self, node_uuid, port_id):
        pass

    def vif_detach(self, node_uuid, port_id):
        pass

    def inject_nmi(self, node_uuid):
        pass

    def list_volume_targets(self, node_uuid, detail=False):
        pass


class FakeClient(object):

    node = FakeNodeClient()
    port = FakePortClient()
    portgroup = FakePortgroupClient()
    volume_target = FakeVolumeTargetClient()
    current_api_version = '%d.%d' % client_wrapper.IRONIC_API_VERSION
    is_api_version_negotiated = True
