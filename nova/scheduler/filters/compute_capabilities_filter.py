# Copyright (c) 2011 OpenStack, LLC.
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
import operator

from nova.openstack.common import log as logging
from nova.scheduler import filters


LOG = logging.getLogger(__name__)


class ComputeCapabilitiesFilter(filters.BaseHostFilter):
    """HostFilter hard-coded to work with InstanceType records."""

    def _satisfies_extra_specs(self, capabilities, instance_type):
        """Check that the capabilities provided by the compute service
        satisfy the extra specs associated with the instance type"""
        if 'extra_specs' not in instance_type:
            return True

        # 1. The following operations are supported:
        #   =, s==, s!=, s>=, s>, s<=, s<, <in>, <or>, ==, !=, >=, <=
        # 2. Note that <or> is handled in a different way below.
        # 3. If the first word in the capability is not one of the operators,
        #   it is ignored.
        op_methods = {'=': lambda x, y: float(x) >= float(y),
                      '<in>': lambda x, y: y in x,
                      '==': lambda x, y: float(x) == float(y),
                      '!=': lambda x, y: float(x) != float(y),
                      '>=': lambda x, y: float(x) >= float(y),
                      '<=': lambda x, y: float(x) <= float(y),
                      's==': operator.eq,
                      's!=': operator.ne,
                      's<': operator.lt,
                      's<=': operator.le,
                      's>': operator.gt,
                      's>=': operator.ge}

        for key, req in instance_type['extra_specs'].iteritems():
            cap = capabilities.get(key, None)
            words = req.split()

            op = method = None
            if words:
                op = words[0]
                method = op_methods.get(op)

            if op != '<or>' and not method:
                if cap != req:
                    return False
                continue

            if cap is None:
                return False

            if op == '<or>':  # Ex: <or> v1 <or> v2 <or> v3
                for idx in range(1, len(words), 2):
                    if words[idx] == cap:
                        break
                else:
                    return False
            else:  # method
                if len(words) == 1:
                    return False
                if not method(cap, words[1]):
                    return False

        return True

    def host_passes(self, host_state, filter_properties):
        """Return a list of hosts that can create instance_type."""
        instance_type = filter_properties.get('instance_type')
        if not self._satisfies_extra_specs(host_state.capabilities,
                instance_type):
            LOG.debug(_("%(host_state)s fails instance_type extra_specs "
                    "requirements"), locals())
            return False
        return True
