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

flags.DECLARE('volume_driver', 'nova.volume.manager')
FLAGS.set_default('volume_driver', 'nova.volume.driver.FakeISCSIDriver')
FLAGS.set_default('connection_type', 'fake')
FLAGS.set_default('fake_rabbit', True)
FLAGS.set_default('rpc_backend', 'nova.rpc.impl_fake')
flags.DECLARE('auth_driver', 'nova.auth.manager')
FLAGS.set_default('auth_driver', 'nova.auth.dbdriver.DbDriver')
flags.DECLARE('network_size', 'nova.network.manager')
flags.DECLARE('num_networks', 'nova.network.manager')
flags.DECLARE('fake_network', 'nova.network.manager')
FLAGS.set_default('network_size', 8)
FLAGS.set_default('num_networks', 2)
FLAGS.set_default('fake_network', True)
FLAGS.set_default('image_service', 'nova.image.fake.FakeImageService')
flags.DECLARE('iscsi_num_targets', 'nova.volume.driver')
FLAGS.set_default('iscsi_num_targets', 8)
FLAGS.set_default('verbose', True)
FLAGS.set_default('sqlite_db', "tests.sqlite")
FLAGS.set_default('use_ipv6', True)
FLAGS.set_default('flat_network_bridge', 'br100')
FLAGS.set_default('sqlite_synchronous', False)
flags.DECLARE('policy_file', 'nova.policy')
FLAGS.set_default('policy_file', 'nova/tests/policy.json')
