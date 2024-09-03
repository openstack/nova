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

from openstack.baremetal.v1 import node as _node
from openstack.baremetal.v1 import port as _port
from openstack.baremetal.v1 import port_group as _port_group
from openstack.baremetal.v1 import volume_connector as _volume_connector
from openstack.baremetal.v1 import volume_target as _volume_target

from nova.network import model as network_model
from nova import objects
from nova.virt import driver
from nova.virt.ironic import ironic_states

# NOTE(JayF): These exist to make it trivial to unify test data
# between both the driver_metadata generators and the generated
# objects.
TEST_IMAGE_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"
TEST_IMAGE_NAME = "test-image"
TEST_FLAVOR_ID = 1
TEST_FLAVOR_NAME = "fake.flavor"
TEST_FLAVOR_EXTRA_SPECS = {
    'baremetal:deploy_kernel_id': 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
    'baremetal:deploy_ramdisk_id': 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'}
TEST_FLAVOR_SWAP = 1
TEST_FLAVOR_ROOTGB = 1
TEST_FLAVOR_MEMORYMB = 1
TEST_FLAVOR_VCPUS = 1
TEST_FLAVOR_EPHEMERALGB = 0


def get_test_validation(**kw):
    result = {
        'power': _node.ValidationResult(result=True, reason=None),
        'deploy': _node.ValidationResult(result=True, reason=None),
        'console': _node.ValidationResult(result=True, reason=None),
        'rescue': _node.ValidationResult(result=True, reason=None),
        'storage': _node.ValidationResult(result=True, reason=None),
    }
    result.update(kw)
    return result


def get_test_node(fields=None, **kw):
    # NOTE(stephenfin): Prevent invalid properties making their way through
    if 'uuid' in kw or 'instance_uuid' in kw or 'maintenance' in kw:
        raise Exception('Invalid property provided')

    node = {
        'id': kw.get('id', 'eeeeeeee-dddd-cccc-bbbb-aaaaaaaaaaaa'),
        'chassis_uuid': kw.get('chassis_uuid'),
        'power_state': kw.get('power_state', ironic_states.NOSTATE),
        'target_power_state': kw.get('target_power_state',
                                     ironic_states.NOSTATE),
        'provision_state': kw.get('provision_state', ironic_states.AVAILABLE),
        'target_provision_state': kw.get('target_provision_state',
                                         ironic_states.NOSTATE),
        'last_error': kw.get('last_error'),
        'instance_id': kw.get('instance_id'),
        'instance_info': kw.get('instance_info'),
        'driver': kw.get('driver', 'fake'),
        'driver_info': kw.get('driver_info', {}),
        'properties': kw.get('properties', {}),
        'reservation': kw.get('reservation'),
        'is_maintenance': kw.get('is_maintenance'),
        'network_interface': kw.get('network_interface'),
        'resource_class': kw.get('resource_class'),
        'traits': kw.get('traits', []),
        'extra': kw.get('extra', {}),
        'updated_at': kw.get('created_at'),
        'created_at': kw.get('updated_at'),
    }

    if fields is not None:
        node = {key: value for key, value in node.items() if key in fields}

    return _node.Node(**node)


def get_test_port(**kw):
    # NOTE(stephenfin): Prevent invalid properties making their way through
    if 'uuid' in kw or 'node_uuid' in kw or 'portgroup_uuid' in kw:
        raise Exception('Invalid property provided')

    port = {
        'id': kw.get('id', 'gggggggg-uuuu-qqqq-ffff-llllllllllll'),
        'node_id': kw.get('node_id', get_test_node().id),
        'address': kw.get('address', 'FF:FF:FF:FF:FF:FF'),
        'extra': kw.get('extra', {}),
        'internal_info': kw.get('internal_info', {}),
        'port_group_id': kw.get('port_group_id'),
        'created_at': kw.get('created_at'),
        'updated_at': kw.get('updated_at'),
    }

    return _port.Port(**port)


def get_test_portgroup(**kw):
    # NOTE(stephenfin): Prevent invalid properties making their way through
    if 'uuid' in kw or 'node_uuid' in kw:
        raise Exception('Invalid property provided')

    port_group = {
        'id': kw.get('id', 'deaffeed-1234-5678-9012-fedcbafedcba'),
        'node_id': kw.get('node_id', get_test_node().id),
        'address': kw.get('address', 'EE:EE:EE:EE:EE:EE'),
        'extra': kw.get('extra', {}),
        'internal_info': kw.get('internal_info', {}),
        'properties': kw.get('properties', {}),
        'mode': kw.get('mode', 'active-backup'),
        'name': kw.get('name'),
        'is_standalone_ports_supported': kw.get(
            'is_standalone_ports_supported', True,
        ),
        'created_at': kw.get('created_at'),
        'updated_at': kw.get('updated_at'),
    }

    return _port_group.PortGroup(**port_group)


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
        'qbg_params': kw.get('qbg_params'),
    }


def get_test_volume_connector(**kw):
    # NOTE(stephenfin): Prevent invalid properties making their way through
    if 'uuid' in kw or 'node_uuid' in kw:
        raise Exception('Invalid property provided')

    volume_connector = {
        'id': kw.get('id', 'hhhhhhhh-qqqq-uuuu-mmmm-bbbbbbbbbbbb'),
        'node_id': kw.get('node_id', get_test_node().id),
        'type': kw.get('type', 'iqn'),
        'connector_id': kw.get('connector_id', 'iqn.test'),
        'extra': kw.get('extra', {}),
        'created_at': kw.get('created_at'),
        'updated_at': kw.get('updated_at'),
    }

    return _volume_connector.VolumeConnector(**volume_connector)


def get_test_volume_target(**kw):
    # NOTE(stephenfin): Prevent invalid properties making their way through
    if 'uuid' in kw or 'node_uuid' in kw:
        raise Exception('Invalid property provided')

    volume_target = {
        'id': kw.get('id', 'aaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'),
        'node_id': kw.get('node_id', get_test_node().id),
        'volume_type': kw.get('volume_type', 'iscsi'),
        'properties': kw.get('properties', {}),
        'boot_index': kw.get('boot_index', 0),
        'volume_id': kw.get(
            'volume_id', 'fffffff-gggg-hhhh-iiii-jjjjjjjjjjjj',
        ),
        'extra': kw.get('extra', {}),
        'created_at': kw.get('created_at'),
        'updated_at': kw.get('updated_at'),
    }

    return _volume_target.VolumeTarget(**volume_target)


def get_test_flavor(**kw):
    flavor = {
        'id': kw.get('id', TEST_FLAVOR_ID),
        'name': kw.get('name', TEST_FLAVOR_NAME),
        'extra_specs': kw.get('extra_specs', TEST_FLAVOR_EXTRA_SPECS),
        'swap': kw.get('swap', TEST_FLAVOR_SWAP),
        'root_gb': TEST_FLAVOR_ROOTGB,
        'memory_mb': TEST_FLAVOR_MEMORYMB,
        'vcpus': TEST_FLAVOR_VCPUS,
        'ephemeral_gb': kw.get('ephemeral_gb', TEST_FLAVOR_EPHEMERALGB),
    }

    return objects.Flavor(**flavor)


def get_test_image_meta(**kw):
    return objects.ImageMeta.from_dict(
        {'id': kw.get('id', TEST_IMAGE_UUID)},
    )


def get_test_instance_driver_metadata(**kw):
    default_instance_meta = driver.NovaInstanceMeta(
        name=kw.get('instance_name', 'testinstance'),
        uuid=kw.get('instance_uuid', 'iiiiiii-iiii-iiii-iiii-iiiiiiiiiiii'))
    default_owner_meta = driver.OwnerMeta(
        userid='uuuuuuu-uuuu-uuuu-uuuu-uuuuuuuuuuuu',
        username='testuser',
        projectid='ppppppp-pppp-pppp-pppp-pppppppppppp',
        projectname='testproject')
    default_image_meta = driver.ImageMeta(id=TEST_IMAGE_UUID,
                                          name=TEST_IMAGE_NAME,
                                          properties={})
    default_flavor_meta = driver.FlavorMeta(
                             name=kw.get('flavor_name', TEST_FLAVOR_NAME),
                             memory_mb=kw.get('flavor_memorymb',
                                              TEST_FLAVOR_MEMORYMB),
                             vcpus=kw.get('flavor_vcpus', TEST_FLAVOR_VCPUS),
                             root_gb=kw.get('flavor_rootgb',
                                            TEST_FLAVOR_ROOTGB),
                             ephemeral_gb=kw.get('flavor_ephemeralgb',
                                                 TEST_FLAVOR_EPHEMERALGB),
                             extra_specs=kw.get('flavor_extra_specs',
                                                TEST_FLAVOR_EXTRA_SPECS),
                             swap=kw.get('flavor_swap', TEST_FLAVOR_SWAP))

    return driver.InstanceDriverMetadata(
        root_type=kw.get('root_type', 'roottype'),
        root_id=kw.get('root_id', 'rootid'),
        instance_meta=kw.get('instance_meta', default_instance_meta),
        owner=kw.get('owner_meta', default_owner_meta),
        image=kw.get('image_meta', default_image_meta),
        flavor=kw.get('flavor_meta', default_flavor_meta),
        network_info=kw.get('network_info', network_model.NetworkInfo())
    )
