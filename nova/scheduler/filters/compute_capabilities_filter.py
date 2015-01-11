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

from oslo_serialization import jsonutils
import six

from nova.openstack.common import log as logging
from nova.scheduler import filters
from nova.scheduler.filters import extra_specs_ops


LOG = logging.getLogger(__name__)


class ComputeCapabilitiesFilter(filters.BaseHostFilter):
    """HostFilter hard-coded to work with InstanceType records."""

    # Instance type and host capabilities do not change within a request
    run_filter_once_per_request = True

    def _get_capabilities(self, host_state, scope):
        cap = host_state
        for index in range(0, len(scope)):
            try:
                if isinstance(cap, six.string_types):
                    try:
                        cap = jsonutils.loads(cap)
                    except ValueError as e:
                        LOG.debug("%(host_state)s fails. The capabilities "
                                  "'%(cap)s' couldn't be loaded from JSON: "
                                  "%(error)s",
                                  {'host_state': host_state, 'cap': cap,
                                   'error': e})
                        return None
                if not isinstance(cap, dict):
                    if getattr(cap, scope[index], None) is None:
                        # If can't find, check stats dict
                        cap = cap.stats.get(scope[index], None)
                    else:
                        cap = getattr(cap, scope[index], None)
                else:
                    cap = cap.get(scope[index], None)
            except AttributeError as e:
                LOG.debug("%(host_state)s fails. The capabilities couldn't "
                          "be retrieved: %(error)s.",
                          {'host_state': host_state, 'error': e})
                return None
            if cap is None:
                LOG.debug("%(host_state)s fails. There are no capabilities "
                          "to retrieve.",
                          {'host_state': host_state})
                return None
        return cap

    def _satisfies_extra_specs(self, host_state, instance_type):
        """Check that the host_state provided by the compute service
        satisfy the extra specs associated with the instance type.
        """
        if 'extra_specs' not in instance_type:
            return True

        for key, req in instance_type['extra_specs'].iteritems():
            # Either not scope format, or in capabilities scope
            scope = key.split(':')
            if len(scope) > 1:
                if scope[0] != "capabilities":
                    continue
                else:
                    del scope[0]

            cap = self._get_capabilities(host_state, scope)
            if cap is None:
                return False

            if not extra_specs_ops.match(str(cap), req):
                LOG.debug("%(host_state)s fails extra_spec requirements. "
                          "'%(req)s' does not match '%(cap)s'",
                          {'host_state': host_state, 'req': req,
                           'cap': cap})
                return False
        return True

    def host_passes(self, host_state, filter_properties):
        """Return a list of hosts that can create instance_type."""
        instance_type = filter_properties.get('instance_type')
        if not self._satisfies_extra_specs(host_state,
                instance_type):
            LOG.debug("%(host_state)s fails instance_type extra_specs "
                      "requirements", {'host_state': host_state})
            return False
        return True
