# Copyright (c) 2012 OpenStack, LLC.
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

from nova.openstack.common import cfg
from nova.openstack.common import log as logging
from nova.scheduler import filters
from nova import servicegroup

CONF = cfg.CONF

LOG = logging.getLogger(__name__)


class ComputeFilter(filters.BaseHostFilter):
    """Filter on active Compute nodes"""

    def __init__(self):
        self.servicegroup_api = servicegroup.API()

    def host_passes(self, host_state, filter_properties):
        """Returns True for only active compute nodes"""
        capabilities = host_state.capabilities
        service = host_state.service

        alive = self.servicegroup_api.service_is_up(service)
        if not alive or service['disabled']:
            LOG.debug(_("%(host_state)s is disabled or has not been "
                    "heard from in a while"), locals())
            return False
        if not capabilities.get("enabled", True):
            LOG.debug(_("%(host_state)s is disabled via capabilities"),
                    locals())
            return False
        return True
