# Copyright 2018 Red Hat, Inc.
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

import nova.conf
from nova import test


CONF = nova.conf.CONF


class NeutronConfTestCase(test.NoDBTestCase):

    def test_register_dynamic_opts(self):
        self.flags(physnets=['foo', 'bar', 'baz'], group='neutron')

        self.assertNotIn('neutron_physnet_foo', CONF)
        self.assertNotIn('neutron_physnet_bar', CONF)

        nova.conf.neutron.register_dynamic_opts(CONF)

        self.assertIn('neutron_physnet_foo', CONF)
        self.assertIn('neutron_physnet_bar', CONF)
        self.assertIn('neutron_tunnel', CONF)
        self.assertIn('numa_nodes', CONF.neutron_tunnel)
