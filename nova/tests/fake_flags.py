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
FLAGS.volume_driver = 'nova.volume.driver.FakeISCSIDriver'
FLAGS.connection_type = 'fake'
FLAGS.fake_rabbit = True
flags.DECLARE('auth_driver', 'nova.auth.manager')
FLAGS.auth_driver = 'nova.auth.dbdriver.DbDriver'
flags.DECLARE('network_size', 'nova.network.manager')
flags.DECLARE('num_networks', 'nova.network.manager')
flags.DECLARE('fake_network', 'nova.network.manager')
FLAGS.network_size = 8
FLAGS.num_networks = 2
FLAGS.fake_network = True
FLAGS.image_service = 'nova.image.local.LocalImageService'
flags.DECLARE('num_shelves', 'nova.volume.driver')
flags.DECLARE('blades_per_shelf', 'nova.volume.driver')
flags.DECLARE('iscsi_num_targets', 'nova.volume.driver')
FLAGS.num_shelves = 2
FLAGS.blades_per_shelf = 4
FLAGS.iscsi_num_targets = 8
FLAGS.verbose = True
FLAGS.sqlite_db = "tests.sqlite"
FLAGS.use_ipv6 = True
