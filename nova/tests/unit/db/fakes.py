# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2010 OpenStack Foundation
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

"""Stubouts, mocks and fixtures for the test suite."""

import datetime


def stub_out(test, funcs):
    """Set the stubs in mapping in the db api."""
    for module, func in funcs.items():
        test.stub_out(module, func)


def stub_out_db_instance_api(test, injected=True):
    """Stubs out the db API for creating Instances."""

    def _create_instance_type(**updates):
        instance_type = {'id': 2,
                         'name': 'm1.tiny',
                         'memory_mb': 512,
                         'vcpus': 1,
                         'vcpu_weight': None,
                         'root_gb': 0,
                         'ephemeral_gb': 10,
                         'flavorid': 1,
                         'rxtx_factor': 1.0,
                         'swap': 0,
                         'deleted_at': None,
                         'created_at': datetime.datetime(2014, 8, 8, 0, 0, 0),
                         'updated_at': None,
                         'deleted': False,
                         'disabled': False,
                         'is_public': True,
                         'extra_specs': {},
                         'description': None
                        }
        if updates:
            instance_type.update(updates)
        return instance_type

    INSTANCE_TYPES = {
        'm1.tiny': _create_instance_type(
                        id=2,
                        name='m1.tiny',
                        memory_mb=512,
                        vcpus=1,
                        vcpu_weight=None,
                        root_gb=0,
                        ephemeral_gb=10,
                        flavorid=1,
                        rxtx_factor=1.0,
                        swap=0),
        'm1.small': _create_instance_type(
                        id=5,
                        name='m1.small',
                        memory_mb=2048,
                        vcpus=1,
                        vcpu_weight=None,
                        root_gb=20,
                        ephemeral_gb=0,
                        flavorid=2,
                        rxtx_factor=1.0,
                        swap=1024),
        'm1.medium': _create_instance_type(
                        id=1,
                         name='m1.medium',
                         memory_mb=4096,
                         vcpus=2,
                         vcpu_weight=None,
                         root_gb=40,
                         ephemeral_gb=40,
                         flavorid=3,
                         rxtx_factor=1.0,
                         swap=0),
        'm1.large': _create_instance_type(
                        id=3,
                         name='m1.large',
                         memory_mb=8192,
                         vcpus=4,
                         vcpu_weight=10,
                         root_gb=80,
                         ephemeral_gb=80,
                         flavorid=4,
                         rxtx_factor=1.0,
                         swap=0),
        'm1.xlarge': _create_instance_type(
                         id=4,
                         name='m1.xlarge',
                         memory_mb=16384,
                         vcpus=8,
                         vcpu_weight=None,
                         root_gb=160,
                         ephemeral_gb=160,
                         flavorid=5,
                         rxtx_factor=1.0,
                         swap=0)}

    def fake_flavor_get_all(*a, **k):
        return INSTANCE_TYPES.values()

    @classmethod
    def fake_flavor_get_by_name(cls, context, name):
        return INSTANCE_TYPES[name]

    @classmethod
    def fake_flavor_get(cls, context, id):
        for inst_type in INSTANCE_TYPES.values():
            if str(inst_type['id']) == str(id):
                return inst_type
        return None

    funcs = {
        'nova.objects.flavor._flavor_get_all_from_db': (
            fake_flavor_get_all),
        'nova.objects.Flavor._flavor_get_by_name_from_db': (
            fake_flavor_get_by_name),
        'nova.objects.Flavor._flavor_get_from_db': fake_flavor_get,
    }
    stub_out(test, funcs)
