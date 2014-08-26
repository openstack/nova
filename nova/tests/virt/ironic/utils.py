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

from nova.virt.ironic import ironic_states


def get_test_validation(**kw):
    return type('interfaces', (object,),
               {'power': kw.get('power', True),
                'deploy': kw.get('deploy', True),
                'console': kw.get('console', True),
                'rescue': kw.get('rescue', True)})()


def get_test_node(**kw):
    return type('node', (object,),
               {'uuid': kw.get('uuid', 'eeeeeeee-dddd-cccc-bbbb-aaaaaaaaaaaa'),
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
                'instance_uuid': kw.get('instance_uuid'),
                'driver': kw.get('driver', 'fake'),
                'driver_info': kw.get('driver_info', {}),
                'properties': kw.get('properties', {}),
                'reservation': kw.get('reservation'),
                'maintenance': kw.get('maintenance', False),
                'extra': kw.get('extra', {}),
                'updated_at': kw.get('created_at'),
                'created_at': kw.get('updated_at')})()


def get_test_port(**kw):
    return type('port', (object,),
               {'uuid': kw.get('uuid', 'gggggggg-uuuu-qqqq-ffff-llllllllllll'),
                'node_uuid': kw.get('node_uuid', get_test_node().uuid),
                'address': kw.get('address', 'FF:FF:FF:FF:FF:FF'),
                'extra': kw.get('extra', {}),
                'created_at': kw.get('created_at'),
                'updated_at': kw.get('updated_at')})()


def get_test_flavor(**kw):
    default_extra_specs = {'baremetal:deploy_kernel_id':
                                       'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                           'baremetal:deploy_ramdisk_id':
                                       'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb'}
    return {'name': kw.get('name', 'fake.flavor'),
            'extra_specs': kw.get('extra_specs', default_extra_specs),
            'swap': kw.get('swap', 0),
            'ephemeral_gb': kw.get('ephemeral_gb', 0)}


def get_test_image_meta(**kw):
    return {'id': kw.get('id', 'cccccccc-cccc-cccc-cccc-cccccccccccc')}


class FakePortClient(object):

    def get(self, port_uuid):
        pass

    def update(self, port_uuid, patch):
        pass


class FakeNodeClient(object):

    def list(self, detail=False):
        return []

    def get(self, node_uuid):
        pass

    def get_by_instance_uuid(self, instance_uuid):
        pass

    def list_ports(self, node_uuid):
        pass

    def set_power_state(self, node_uuid, target):
        pass

    def set_provision_state(self, node_uuid, target):
        pass

    def update(self, node_uuid, patch):
        pass

    def validate(self, node_uuid):
        pass


class FakeClient(object):

    node = FakeNodeClient()
    port = FakePortClient()
