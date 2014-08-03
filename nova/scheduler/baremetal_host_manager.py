# Copyright (c) 2012 NTT DOCOMO, INC.
# Copyright (c) 2011 OpenStack Foundation
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

"""
Manage hosts in the current zone.
"""

import nova.scheduler.base_baremetal_host_manager as bbhm
from nova.scheduler import host_manager


class BaremetalNodeState(bbhm.BaseBaremetalNodeState):
    """Mutable and immutable information tracked for a host.
    This is an attempt to remove the ad-hoc data structures
    previously used and lock down access.
    """
    pass


class BaremetalHostManager(bbhm.BaseBaremetalHostManager):
    """Bare-Metal HostManager class."""

    def host_state_cls(self, host, node, **kwargs):
        """Factory function/property to create a new HostState."""
        compute = kwargs.get('compute')
        if compute and compute.get('cpu_info') == 'baremetal cpu':
            return BaremetalNodeState(host, node, **kwargs)
        else:
            return host_manager.HostState(host, node, **kwargs)
