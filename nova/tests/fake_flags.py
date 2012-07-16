# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from nova import flags

FLAGS = flags.FLAGS

flags.DECLARE('compute_scheduler_driver', 'nova.scheduler.multi')
flags.DECLARE('fake_network', 'nova.network.manager')
flags.DECLARE('iscsi_num_targets', 'nova.volume.driver')
flags.DECLARE('network_size', 'nova.network.manager')
flags.DECLARE('num_networks', 'nova.network.manager')
flags.DECLARE('policy_file', 'nova.policy')
flags.DECLARE('volume_driver', 'nova.volume.manager')


def set_defaults(conf):
    conf.set_default('api_paste_config', '$state_path/etc/nova/api-paste.ini')
    conf.set_default('compute_driver', 'nova.virt.fake.FakeDriver')
    conf.set_default('connection_type', 'fake')
    conf.set_default('fake_network', True)
    conf.set_default('fake_rabbit', True)
    conf.set_default('flat_network_bridge', 'br100')
    conf.set_default('iscsi_num_targets', 8)
    conf.set_default('network_size', 8)
    conf.set_default('num_networks', 2)
    conf.set_default('vlan_interface', 'eth0')
    conf.set_default('rpc_backend', 'nova.openstack.common.rpc.impl_fake')
    conf.set_default('sql_connection', "sqlite://")
    conf.set_default('sqlite_synchronous', False)
    conf.set_default('use_ipv6', True)
    conf.set_default('verbose', True)
    conf.set_default('volume_driver', 'nova.volume.driver.FakeISCSIDriver')
    conf.set_default('api_paste_config', '$state_path/etc/nova/api-paste.ini')
    conf.set_default('rpc_response_timeout', 5)
    conf.set_default('rpc_cast_timeout', 5)
    conf.set_default('lock_path', None)
