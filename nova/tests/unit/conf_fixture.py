# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

from oslo_config import fixture as config_fixture
from oslo_policy import opts as policy_opts

from nova.conf import neutron
from nova.conf import paths
from nova import config
from nova import ipv6
from nova.tests.unit import utils


class ConfFixture(config_fixture.Config):
    """Fixture to manage global conf settings."""
    def setUp(self):
        super(ConfFixture, self).setUp()

        # default group
        self.conf.set_default('compute_driver', 'fake.SmallFakeDriver')
        self.conf.set_default('fake_network', True)
        self.conf.set_default('flat_network_bridge', 'br100')
        self.conf.set_default('floating_ip_dns_manager',
                              'nova.tests.unit.utils.dns_manager')
        self.conf.set_default('force_dhcp_release', False)
        self.conf.set_default('host', 'fake-mini')
        self.conf.set_default('instance_dns_manager',
                              'nova.tests.unit.utils.dns_manager')
        self.conf.set_default('network_size', 8)
        self.conf.set_default('num_networks', 2)
        self.conf.set_default('periodic_enable', False)
        # TODO(sdague): this makes our project_id match 'fake' as well.
        # We should fix the tests to use real
        # UUIDs then drop this work around.
        self.conf.set_default('project_id_regex',
                              '[0-9a-fk\-]+', 'osapi_v21')
        self.conf.set_default('use_ipv6', True)
        self.conf.set_default('vlan_interface', 'eth0')

        # api group
        self.conf.set_default('auth_strategy', 'noauth2', group='api')

        # api_database group
        self.conf.set_default('connection', "sqlite://", group='api_database')
        self.conf.set_default('sqlite_synchronous', False,
                              group='api_database')

        # database group
        self.conf.set_default('connection', "sqlite://", group='database')
        self.conf.set_default('sqlite_synchronous', False, group='database')

        # key_manager group
        self.conf.set_default('backend',
                              'nova.keymgr.conf_key_mgr.ConfKeyManager',
                              group='key_manager')

        # wsgi group
        self.conf.set_default('api_paste_config',
                              paths.state_path_def('etc/nova/api-paste.ini'),
                              group='wsgi')
        # The functional tests run wsgi API services using fixtures and
        # eventlet and we want one connection per request so things don't
        # leak between requests from separate services in concurrently running
        # tests.
        self.conf.set_default('keep_alive', False, group="wsgi")

        config.parse_args([], default_config_files=[], configure_db=False,
                          init_rpc=False)
        policy_opts.set_defaults(self.conf)
        neutron.register_dynamic_opts(self.conf)
        self.addCleanup(utils.cleanup_dns_managers)
        self.addCleanup(ipv6.api.reset_backend)
