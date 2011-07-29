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
FLAGS['volume_driver'].SetDefault('nova.volume.driver.FakeISCSIDriver')
FLAGS['connection_type'].SetDefault('fake')
FLAGS['fake_rabbit'].SetDefault(True)
flags.DECLARE('auth_driver', 'nova.auth.manager')
FLAGS['auth_driver'].SetDefault('nova.auth.dbdriver.DbDriver')
flags.DECLARE('network_size', 'nova.network.manager')
flags.DECLARE('num_networks', 'nova.network.manager')
flags.DECLARE('fake_network', 'nova.network.manager')
FLAGS['network_size'].SetDefault(8)
FLAGS['num_networks'].SetDefault(2)
FLAGS['fake_network'].SetDefault(True)
FLAGS['image_service'].SetDefault('nova.image.fake.FakeImageService')
flags.DECLARE('num_shelves', 'nova.volume.driver')
flags.DECLARE('blades_per_shelf', 'nova.volume.driver')
flags.DECLARE('iscsi_num_targets', 'nova.volume.driver')
FLAGS['num_shelves'].SetDefault(2)
FLAGS['blades_per_shelf'].SetDefault(4)
FLAGS['iscsi_num_targets'].SetDefault(8)
FLAGS['verbose'].SetDefault(True)
FLAGS['sqlite_db'].SetDefault("tests.sqlite")
FLAGS['use_ipv6'].SetDefault(True)
FLAGS['flat_network_bridge'].SetDefault('br100')
