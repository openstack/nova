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

from nova.virt.libvirt.cpu import api


Core = api.Core


power_up = api.power_up
power_down = api.power_down
validate_all_dedicated_cpus = api.validate_all_dedicated_cpus
power_down_all_dedicated_cpus = api.power_down_all_dedicated_cpus
