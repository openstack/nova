# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 OpenStack, LLC.
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

"""Compute-related Utilities and helpers."""

from nova import context
from nova import db
from nova import flags
from nova.notifier import api as notifier_api
from nova import utils


FLAGS = flags.FLAGS


def notify_usage_exists(instance_ref, current_period=False):
    """ Generates 'exists' notification for an instance for usage auditing
        purposes.

        Generates usage for last completed period, unless 'current_period'
        is True."""
    admin_context = context.get_admin_context()
    begin, end = utils.current_audit_period()
    bw = {}
    if current_period:
        audit_start = end
        audit_end = utils.utcnow()
    else:
        audit_start = begin
        audit_end = end
    for b in db.bw_usage_get_by_instance(admin_context,
                                         instance_ref['id'],
                                         audit_start):
        bw[b.network_label] = dict(bw_in=b.bw_in, bw_out=b.bw_out)
    usage_info = utils.usage_from_instance(instance_ref,
                          audit_period_beginning=str(audit_start),
                          audit_period_ending=str(audit_end),
                          bandwidth=bw)
    notifier_api.notify('compute.%s' % FLAGS.host,
                        'compute.instance.exists',
                        notifier_api.INFO,
                        usage_info)
