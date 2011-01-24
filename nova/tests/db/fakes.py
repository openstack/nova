# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack, LLC
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

"""Stubouts, mocks and fixtures for the test suite"""

import time

from nova import db
from nova import utils
from nova.compute import instance_types


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


def stub_out_db_instance_api(stubs):
    """ Stubs out the db API for creating Instances """

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
            'key_data': None,
            'memory_mb': type_data['memory_mb'],
            'mac_address': values['mac_address'],
            'vcpus': type_data['vcpus'],
            'local_gb': type_data['local_gb'],
            }
        return FakeModel(base_options)

    stubs.Set(db, 'instance_create', fake_instance_create)


def stub_out_db_network_api(stubs, injected=False):
    """Stubs out the db API for retrieving networks"""
    network_fields = {
        'bridge': 'xenbr0',
        'injected': injected}

    if injected:
        network_fields.update({
            'netmask': '255.255.255.0',
            'gateway': '10.0.0.1',
            'broadcast': '10.0.0.255',
            'dns': '10.0.0.2',
            'ra_server': None})

    def fake_network_get_by_instance(context, instance_id):
        return FakeModel(network_fields)

    def fake_instance_get_fixed_address(context, instance_id):
        return '10.0.0.3'

    stubs.Set(db, 'network_get_by_instance', fake_network_get_by_instance)
    stubs.Set(db, 'instance_get_fixed_address',
        fake_instance_get_fixed_address)
