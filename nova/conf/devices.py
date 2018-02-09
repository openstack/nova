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

from oslo_config import cfg

devices_group = cfg.OptGroup(
    name='devices',
    title='physical or virtual device options')

vgpu_opts = [
    cfg.ListOpt('enabled_vgpu_types',
        default=[],
        help="""
A list of the vGPU types enabled in the compute node.

Some pGPUs (e.g. NVIDIA GRID K1) support different vGPU types. User can use
this option to specify a list of enabled vGPU types that may be assigned to a
guest instance. But please note that Nova only supports a single type in the
Queens release. If more than one vGPU type is specified (as a comma-separated
list), only the first one will be used. An example is as the following:
    [devices]
    enabled_vgpu_types = GRID K100,Intel GVT-g,MxGPU.2,nvidia-11
""")
]


def register_opts(conf):
    conf.register_group(devices_group)
    conf.register_opts(vgpu_opts, group=devices_group)


def list_opts():
    return {devices_group: vgpu_opts}
