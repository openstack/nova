# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack LLC.
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

import time

from nova import db
from nova import utils
from nova.compute import instance_types


def stub_out_db_instance_api(stubs):
    """ Stubs out the db API for creating Instances """

    class FakeModel(object):
        """ Stubs out for model """

        def __init__(self, values):
            self.values = values

        def __getattr__(self, name):
            return self.values[name]

        def __getitem__(self, key):
            if key in self.values:
                return self.values[key]
            else:
                raise NotImplementedError()

    def fake_instance_create(values):
        """ Stubs out the db.instance_create method """

        type_data = instance_types.INSTANCE_TYPES[values['instance_type']]

        base_options = {
            'name': values['name'],
            'id': values['id'],
            'reservation_id': utils.generate_uid('r'),
            'image_id': values['image_id'],
            'kernel_id': values['kernel_id'],
            'ramdisk_id': values['ramdisk_id'],
            'state_description': 'scheduling',
            'user_id': values['user_id'],
            'project_id': values['project_id'],
            'launch_time': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
            'instance_type': values['instance_type'],
            'memory_mb': type_data['memory_mb'],
            'mac_address': values['mac_address'],
            'vcpus': type_data['vcpus'],
            'local_gb': type_data['local_gb'],
            }
        return FakeModel(base_options)

    def fake_network_get_by_instance(context, instance_id):
        """ Stubs out the db.network_get_by_instance method """

        fields = {
            'bridge': 'vmnet0',
            'netmask': '255.255.255.0',
            'gateway': '10.10.10.1',
            'vlan': 100}
        return FakeModel(fields)

    def fake_instance_action_create(context, action):
        """ Stubs out the db.instance_action_create method """
        pass

    def fake_instance_get_fixed_address(context, instance_id):
        """ Stubs out the db.instance_get_fixed_address method """
        return '10.10.10.10'

    stubs.Set(db, 'instance_create', fake_instance_create)
    stubs.Set(db, 'network_get_by_instance', fake_network_get_by_instance)
    stubs.Set(db, 'instance_action_create', fake_instance_action_create)
    stubs.Set(db, 'instance_get_fixed_address',
                fake_instance_get_fixed_address)
