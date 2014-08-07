# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
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

from nova.compute.resources import base
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


class VCPU(base.Resource):
    """VCPU compute resource plugin.

    This is effectively a simple counter based on the vcpu requirement of each
    instance.
    """
    def __init__(self):
        # initialize to a 'zero' resource.
        # reset will be called to set real resource values
        self._total = 0
        self._used = 0

    def reset(self, resources, driver):
        # total vcpu is reset to the value taken from resources.
        self._total = int(resources['vcpus'])
        self._used = 0

    def _get_requested(self, usage):
        return int(usage.get('vcpus', 0))

    def _get_limit(self, limits):
        if limits and 'vcpu' in limits:
            return int(limits.get('vcpu'))

    def test(self, usage, limits):
        requested = self._get_requested(usage)
        limit = self._get_limit(limits)

        LOG.debug('Total CPUs: %(total)d VCPUs, used: %(used).02f VCPUs' %
                  {'total': self._total, 'used': self._used})

        if limit is None:
            # treat resource as unlimited:
            LOG.debug('CPUs limit not specified, defaulting to unlimited')
            return

        free = limit - self._used

        # Oversubscribed resource policy info:
        LOG.debug('CPUs limit: %(limit).02f VCPUs, free: %(free).02f VCPUs' %
                  {'limit': limit, 'free': free})

        if requested > free:
            return ('Free CPUs %(free).02f VCPUs < '
                    'requested %(requested)d VCPUs' %
                    {'free': free, 'requested': requested})

    def add_instance(self, usage):
        requested = int(usage.get('vcpus', 0))
        self._used += requested

    def remove_instance(self, usage):
        requested = int(usage.get('vcpus', 0))
        self._used -= requested

    def write(self, resources):
        resources['vcpus'] = self._total
        resources['vcpus_used'] = self._used

    def report_free(self):
        free_vcpus = self._total - self._used
        LOG.debug('Free VCPUs: %s' % free_vcpus)
