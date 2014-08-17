#  Copyright 2012 Cloudbase Solutions Srl
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
Stubouts, mocks and fixtures for the test suite
"""

import uuid

from nova.compute import task_states
from nova.compute import vm_states
from nova import db
from nova import utils


def get_fake_instance_data(name, project_id, user_id):
    return {'name': name,
            'id': 1,
            'uuid': str(uuid.uuid4()),
            'project_id': project_id,
            'user_id': user_id,
            'image_ref': "1",
            'kernel_id': "1",
            'ramdisk_id': "1",
            'mac_address': "de:ad:be:ef:be:ef",
            'flavor':
            {'name': 'm1.tiny',
             'memory_mb': 512,
             'vcpus': 1,
             'root_gb': 1024,
             'flavorid': 1,
             'rxtx_factor': 1}
            }


def get_fake_image_data(project_id, user_id):
    return {'name': 'image1',
            'id': 1,
            'project_id': project_id,
            'user_id': user_id,
            'image_ref': "1",
            'kernel_id': "1",
            'ramdisk_id': "1",
            'mac_address': "de:ad:be:ef:be:ef",
            'flavor': 'm1.tiny',
            }


def get_fake_volume_info_data(target_portal, volume_id):
    return {
        'driver_volume_type': 'iscsi',
        'data': {
            'volume_id': 1,
            'target_iqn': 'iqn.2010-10.org.openstack:volume-' + volume_id,
            'target_portal': target_portal,
            'target_lun': 1,
            'auth_method': 'CHAP',
        }
    }


def get_fake_block_device_info(target_portal, volume_id):
    return {'block_device_mapping': [{'connection_info': {
                                      'driver_volume_type': 'iscsi',
                                      'data': {'target_lun': 1,
                                      'volume_id': volume_id,
                                      'target_iqn':
                                      'iqn.2010-10.org.openstack:volume-' +
                                      volume_id,
                                      'target_portal': target_portal,
                                      'target_discovered': False}},
                                     'mount_device': 'vda',
                                     'delete_on_termination': False}],
            'root_device_name': 'fake_root_device_name',
            'ephemerals': [],
            'swap': None
            }


def stub_out_db_instance_api(stubs):
    """Stubs out the db API for creating Instances."""

    FLAVORS = {
        'm1.tiny': dict(memory_mb=512, vcpus=1, root_gb=0, flavorid=1),
        'm1.small': dict(memory_mb=2048, vcpus=1, root_gb=20, flavorid=2),
        'm1.medium': dict(memory_mb=4096, vcpus=2, root_gb=40, flavorid=3),
        'm1.large': dict(memory_mb=8192, vcpus=4, root_gb=80, flavorid=4),
        'm1.xlarge': dict(memory_mb=16384, vcpus=8, root_gb=160, flavorid=5)}

    class FakeModel(object):
        """Stubs out for model."""

        def __init__(self, values):
            self.values = values

        def get(self, key, default=None):
            if key in self.values:
                return self.values[key]
            else:
                return default

        def __getattr__(self, name):
            return self.values[name]

        def __getitem__(self, key):
            return self.get(key)

        def __setitem__(self, key, value):
            self.values[key] = value

        def __str__(self):
            return str(self.values)

    def fake_instance_create(context, values):
        """Stubs out the db.instance_create method."""

        if 'flavor' not in values:
            return

        flavor = values['flavor']

        base_options = {
            'name': values['name'],
            'id': values['id'],
            'uuid': str(uuid.uuid4()),
            'reservation_id': utils.generate_uid('r'),
            'image_ref': values['image_ref'],
            'kernel_id': values['kernel_id'],
            'ramdisk_id': values['ramdisk_id'],
            'vm_state': vm_states.BUILDING,
            'task_state': task_states.SCHEDULING,
            'user_id': values['user_id'],
            'project_id': values['project_id'],
            'flavor': flavor,
            'memory_mb': flavor['memory_mb'],
            'vcpus': flavor['vcpus'],
            'mac_addresses': [{'address': values['mac_address']}],
            'root_gb': flavor['root_gb'],
        }
        return FakeModel(base_options)

    def fake_flavor_get_all(context, inactive=0, filters=None):
        return FLAVORS.values()

    def fake_flavor_get_by_name(context, name):
        return FLAVORS[name]

    def fake_block_device_mapping_get_all_by_instance(context, instance_uuid):
        return {}

    stubs.Set(db, 'instance_create', fake_instance_create)
    stubs.Set(db, 'flavor_get_all', fake_flavor_get_all)
    stubs.Set(db, 'flavor_get_by_name', fake_flavor_get_by_name)
    stubs.Set(db, 'block_device_mapping_get_all_by_instance',
              fake_block_device_mapping_get_all_by_instance)
