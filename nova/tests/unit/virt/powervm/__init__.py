# Copyright 2014, 2017 IBM Corp.
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
#
from oslo_utils.fixture import uuidsentinel

from nova.compute import power_state
from nova.compute import vm_states
from nova import objects


TEST_FLAVOR = objects.flavor.Flavor(
    memory_mb=2048,
    swap=0,
    vcpu_weight=None,
    root_gb=10, id=2,
    name=u'm1.small',
    ephemeral_gb=0,
    rxtx_factor=1.0,
    flavorid=uuidsentinel.flav_id,
    vcpus=1)

TEST_INSTANCE = objects.Instance(
    id=1,
    uuid=uuidsentinel.inst_id,
    display_name='Fake Instance',
    root_gb=10,
    ephemeral_gb=0,
    instance_type_id=TEST_FLAVOR.id,
    system_metadata={'image_os_distro': 'rhel'},
    host='host1',
    flavor=TEST_FLAVOR,
    task_state=None,
    vm_state=vm_states.STOPPED,
    power_state=power_state.SHUTDOWN,
)

IMAGE1 = {
    'id': uuidsentinel.img_id,
    'name': 'image1',
    'size': 300,
    'container_format': 'bare',
    'disk_format': 'raw',
    'checksum': 'b518a8ba2b152b5607aceb5703fac072',
}
TEST_IMAGE1 = objects.image_meta.ImageMeta.from_dict(IMAGE1)
