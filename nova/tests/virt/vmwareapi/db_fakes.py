# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack Foundation
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

from nova.compute import task_states
from nova.compute import vm_states
from nova import db
from nova import utils


def stub_out_db_instance_api(stubs):
    """Stubs out the db API for creating Instances."""

    INSTANCE_TYPES = {
        'm1.tiny': dict(memory_mb=512, vcpus=1, root_gb=0, flavorid=1),
        'm1.small': dict(memory_mb=2048, vcpus=1, root_gb=20, flavorid=2),
        'm1.medium':
            dict(memory_mb=4096, vcpus=2, root_gb=40, flavorid=3),
        'm1.large': dict(memory_mb=8192, vcpus=4, root_gb=80, flavorid=4),
        'm1.xlarge':
            dict(memory_mb=16384, vcpus=8, root_gb=160, flavorid=5)}

    class FakeModel(object):
        """Stubs out for model."""

        def __init__(self, values):
            self.values = values

        def __getattr__(self, name):
            return self.values[name]

        def get(self, attr):
            try:
                return self.__getattr__(attr)
            except KeyError:
                return None

        def __getitem__(self, key):
            if key in self.values:
                return self.values[key]
            else:
                raise NotImplementedError()

    def fake_instance_create(context, values):
        """Stubs out the db.instance_create method."""

        type_data = INSTANCE_TYPES[values['instance_type']]

        base_options = {
            'name': values['name'],
            'id': values['id'],
            'uuid': values['uuid'],
            'reservation_id': utils.generate_uid('r'),
            'image_ref': values['image_ref'],
            'kernel_id': values['kernel_id'],
            'ramdisk_id': values['ramdisk_id'],
            'vm_state': vm_states.BUILDING,
            'task_state': task_states.SCHEDULING,
            'user_id': values['user_id'],
            'project_id': values['project_id'],
            'instance_type': values['instance_type'],
            'memory_mb': type_data['memory_mb'],
            'vcpus': type_data['vcpus'],
            'mac_addresses': [{'address': values['mac_address']}],
            'root_gb': type_data['root_gb'],
            'node': values['node'],
            }

        return base_options

    def fake_flavor_get_all(context, inactive=0, filters=None):
        return INSTANCE_TYPES.values()

    def fake_flavor_get_by_name(context, name):
        return INSTANCE_TYPES[name]

    stubs.Set(db, 'instance_create', fake_instance_create)
    stubs.Set(db, 'flavor_get_all', fake_flavor_get_all)
    stubs.Set(db, 'flavor_get_by_name', fake_flavor_get_by_name)
