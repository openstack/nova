# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack Foundation
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

from oslo.config import cfg

from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)

virt_cpu_opts = [
    cfg.StrOpt('vcpu_pin_set',
                help='Which pcpus can be used by vcpus of instance '
                     'e.g: "4-12,^8,15"',
                deprecated_group='libvirt'),
]

CONF = cfg.CONF
CONF.register_opts(virt_cpu_opts)


def get_cpuset_ids():
    """
    Parsing vcpu_pin_set config.

    Returns a list of pcpu ids can be used by instances.
    """
    if not CONF.vcpu_pin_set:
        return None

    cpuset_ids = set()
    cpuset_reject_ids = set()
    for rule in CONF.vcpu_pin_set.split(','):
        rule = rule.strip()
        # Handle multi ','
        if len(rule) < 1:
            continue
        # Note the count limit in the .split() call
        range_parts = rule.split('-', 1)
        if len(range_parts) > 1:
            # So, this was a range; start by converting the parts to ints
            try:
                start, end = [int(p.strip()) for p in range_parts]
            except ValueError:
                raise exception.Invalid(_("Invalid range expression %r")
                                        % rule)
            # Make sure it's a valid range
            if start > end:
                raise exception.Invalid(_("Invalid range expression %r")
                                        % rule)
            # Add available pcpu ids to set
            cpuset_ids |= set(range(start, end + 1))
        elif rule[0] == '^':
            # Not a range, the rule is an exclusion rule; convert to int
            try:
                cpuset_reject_ids.add(int(rule[1:].strip()))
            except ValueError:
                raise exception.Invalid(_("Invalid exclusion "
                                          "expression %r") % rule)
        else:
            # OK, a single PCPU to include; convert to int
            try:
                cpuset_ids.add(int(rule))
            except ValueError:
                raise exception.Invalid(_("Invalid inclusion "
                                          "expression %r") % rule)
    # Use sets to handle the exclusion rules for us
    cpuset_ids -= cpuset_reject_ids
    if not cpuset_ids:
        raise exception.Invalid(_("No CPUs available after parsing %r") %
                                CONF.vcpu_pin_set)
    # This will convert the set to a sorted list for us
    return sorted(cpuset_ids)
