# Copyright 2014 Intel Corp.
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

from nova.api.openstack import extensions


class Hypervisor_status(extensions.ExtensionDescriptor):
    """Show hypervisor status."""

    name = "HypervisorStatus"
    alias = "os-hypervisor-status"
    namespace = ("http://docs.openstack.org/compute/ext/"
                "hypervisor_status/api/v1.1")
    updated = "2014-04-17T00:00:00Z"
