# Copyright (c) 2017 Mirantis Inc.
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

from nova import objects


def fake_diagnostics_obj(**updates):
    diag = objects.Diagnostics()
    cpu_details = updates.pop('cpu_details', [])
    nic_details = updates.pop('nic_details', [])
    disk_details = updates.pop('disk_details', [])
    memory_details = updates.pop('memory_details', {})

    for field in objects.Diagnostics.fields:
        if field in updates:
            setattr(diag, field, updates[field])

    for cpu in cpu_details:
        diag.add_cpu(**cpu)

    for nic in nic_details:
        diag.add_nic(**nic)

    for disk in disk_details:
        diag.add_disk(**disk)

    for k, v in memory_details.items():
        setattr(diag.memory_details, k, v)

    return diag
