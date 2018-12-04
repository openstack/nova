# Copyright (c) 2015 Cloudbase Solutions SRL
# All Rights Reserved
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

# NOTE(mikal): this migration number exists like this because change
# I506dd1c8d0f0a877fdfc1a4ed11a8830d9600b98 needs to revert the hyper-v
# keypair change, but we promise that we will never remove a schema migration
# version. Instead, we replace this migration with a noop.
#
# It is hypothetically possible that a hyper-v continuous deployer exists who
# will have a poor experience because of this code revert, if that deployer
# is you, please contact the nova team at openstack-discuss@lists.openstack.org
# and we will walk you through the manual fix required for this problem.


def upgrade(migrate_engine):
    pass
