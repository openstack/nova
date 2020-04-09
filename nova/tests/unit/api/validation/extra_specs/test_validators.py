# Copyright 2020 Red Hat, Inc. All rights reserved.
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

import ddt
import testtools

from nova.api.validation.extra_specs import validators
from nova import exception
from nova import test


@ddt.ddt
class TestValidators(test.NoDBTestCase):

    @ddt.data('strict', 'permissive', 'disabled')
    def test_spec(self, policy):
        invalid_specs = (
            ('hw:cpu_realtime_maskk', '^0'),
            ('hhw:cpu_realtime_mask', '^0'),
            ('w:cpu_realtime_mask', '^0'),
            ('hw:cpu_realtime_mas', '^0'),
            ('hw_cpu_realtime_mask', '^0'),
            ('foo', 'bar'),
        )
        for key, value in invalid_specs:
            if policy == 'strict':
                with testtools.ExpectedException(exception.ValidationError):
                    validators.validate(key, value, policy)
            else:
                validators.validate(key, value, policy)

    @ddt.data('strict', 'permissive', 'disabled')
    def test_value__str(self, policy):
        valid_specs = (
            # patterns
            ('hw:cpu_realtime_mask', '^0'),
            ('hw:cpu_realtime_mask', '^0,2-3,1'),
            ('hw:mem_page_size', 'large'),
            ('hw:mem_page_size', '2kbit'),
            ('hw:mem_page_size', '1GB'),
            # enums
            ('hw:cpu_thread_policy', 'prefer'),
            ('hw:emulator_threads_policy', 'isolate'),
            ('hw:pci_numa_affinity_policy', 'legacy'),
        )
        for key, value in valid_specs:
            validators.validate(key, value, policy)

        invalid_specs = (
            # patterns
            ('hw:cpu_realtime_mask', '0'),
            ('hw:cpu_realtime_mask', '^0,2-3,b'),
            ('hw:mem_page_size', 'largest'),
            ('hw:mem_page_size', '2kbits'),
            ('hw:mem_page_size', '1gigabyte'),
            # enums
            ('hw:cpu_thread_policy', 'preferred'),
            ('hw:emulator_threads_policy', 'iisolate'),
            ('hw:pci_numa_affinity_policy', 'lgacy'),
        )
        for key, value in invalid_specs:
            if policy in ('strict', 'permissive'):
                with testtools.ExpectedException(exception.ValidationError):
                    validators.validate(key, value, policy)
            else:
                validators.validate(key, value, policy)

    @ddt.data('strict', 'permissive', 'disabled')
    def test_value__int(self, policy):
        valid_specs = (
            ('hw:numa_nodes', '1'),
            ('os:monitors', '1'),
            ('powervm:shared_weight', '1'),
            ('os:monitors', '8'),
            ('powervm:shared_weight', '255'),
        )
        for key, value in valid_specs:
            validators.validate(key, value, 'strict')

        invalid_specs = (
            ('hw:serial_port_count', 'five'),  # NaN
            ('hw:serial_port_count', '!'),  # NaN
            ('hw:numa_nodes', '0'),  # has min
            ('os:monitors', '0'),  # has min
            ('powervm:shared_weight', '-1'),  # has min
            ('os:monitors', '9'),  # has max
            ('powervm:shared_weight', '256'),  # has max
        )
        for key, value in invalid_specs:
            if policy in ('strict', 'permissive'):
                with testtools.ExpectedException(exception.ValidationError):
                    validators.validate(key, value, policy)
            else:
                validators.validate(key, value, policy)

    @ddt.data('strict', 'permissive', 'disabled')
    def test_value__bool(self, policy):
        valid_specs = (
            ('hw:cpu_realtime', '1'),
            ('hw:cpu_realtime', '0'),
            ('hw:mem_encryption', 'true'),
            ('hw:boot_menu', 'y'),
        )
        for key, value in valid_specs:
            validators.validate(key, value, 'strict')

        invalid_specs = (
            ('hw:cpu_realtime', '2'),
            ('hw:cpu_realtime', '00'),
            ('hw:mem_encryption', 'tru'),
            ('hw:boot_menu', 'yah'),
        )
        for key, value in invalid_specs:
            if policy in ('strict', 'permissive'):
                with testtools.ExpectedException(exception.ValidationError):
                    validators.validate(key, value, policy)
            else:
                validators.validate(key, value, policy)
