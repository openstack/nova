# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2011 Midokura KK
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

"""VIF module common to all virt layers."""


class VIFDriver(object):
    """Abstract class that defines generic interfaces for all VIF drivers."""

    def plug(self, instance, network, mapping):
        """Plug VIF into network."""
        raise NotImplementedError()

    def unplug(self, instance, network, mapping):
        """Unplug VIF from network."""
        raise NotImplementedError()
