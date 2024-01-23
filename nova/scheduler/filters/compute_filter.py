# Copyright (c) 2012 OpenStack Foundation
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

from oslo_log import log as logging

from nova.scheduler import filters
from nova import servicegroup
from ..manager import CORE_USAGE

LOG = logging.getLogger(__name__)


class ComputeFilter(filters.BaseHostFilter):
    """Filter on active Compute nodes."""

    RUN_ON_REBUILD = False

    def __init__(self):
        self.servicegroup_api = servicegroup.API()

    # Host state does not change within a request
    run_filter_once_per_request = True

    def host_passes(self, host_state, spec_obj):
        """Returns True for only active compute nodes."""

        service = host_state.service
        if service['disabled']:
            LOG.debug("%(host_state)s is disabled, reason: %(reason)s",
                      {'host_state': host_state,
                       'reason': service.get('disabled_reason')})
            return False
        else:
            if not self.servicegroup_api.service_is_up(service):
                LOG.warning("%(host_state)s has not been heard from in a "
                            "while", {'host_state': host_state})
                return False
        LOG.debug("tharindu-green-cores@ccompute_filter: spec_obj %(spec_obj)s", {'spec_obj': spec_obj})
        LOG.debug("tharindu-green-cores@ccompute_filter: CORE_USAGE %(CORE_USAGE)s", {'CORE_USAGE': CORE_USAGE})
        LOG.debug("tharindu-green-cores: CORE_USAGE['core_usage'] %(spec_obj)s", {'spec_obj': CORE_USAGE['core_usage']})
        LOG.debug("tharindu-green-cores@ccompute_filter: host ip %(ip)s", {'ip': host_state.host_ip})

        host_ip = host_state.host_ip
        core_usage = list(filter(lambda x: x['host-ip'] == str(host_ip), CORE_USAGE['core_usage']))
        LOG.debug("tharindu-green-cores@ccompute_filter: host_ip %(host_ip)s", {'host_ip': host_ip})
        LOG.debug("tharindu-green-cores@ccompute_filter: core_usage %(core_usage)s", {'core_usage': core_usage})
        core_usage = core_usage[0]

        rcpus_avl = core_usage['reg-cores-avl']
        rcpus_usg = core_usage['reg-cores-usg']
        rcpus_free = rcpus_avl - rcpus_usg

        hints = spec_obj.scheduler_hints
        type = hints['type'][0]
        LOG.debug("tharindu-green-cores@ccompute_filter: type %(type)s", {'type': type})
        LOG.debug("tharindu-green-cores@ccompute_filter: rcpus_free %(rcpus_free)s", {'rcpus_free': rcpus_free})
        LOG.debug("tharindu-green-cores@ccompute_filter: spec_obj.vcpus %(spec_obj.vcpus)s", {'spec_obj.vcpus': spec_obj.vcpus})
        if type == 'regular' and rcpus_free < spec_obj.vcpus:
            return False

        return True
