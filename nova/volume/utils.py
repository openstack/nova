# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 OpenStack, LLC.
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

"""Volume-related Utilities and helpers."""

from nova import flags
from nova.openstack.common import log as logging
from nova.openstack.common.notifier import api as notifier_api
from nova.openstack.common import timeutils
from nova import utils


FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)


def notify_usage_exists(context, volume_ref, current_period=False):
    """ Generates 'exists' notification for a volume for usage auditing
        purposes.

        Generates usage for last completed period, unless 'current_period'
        is True."""
    begin, end = utils.last_completed_audit_period()
    if current_period:
        audit_start = end
        audit_end = timeutils.utcnow()
    else:
        audit_start = begin
        audit_end = end

    extra_usage_info = dict(audit_period_beginning=str(audit_start),
                            audit_period_ending=str(audit_end))

    notify_about_volume_usage(
            context, volume_ref, 'exists', extra_usage_info=extra_usage_info)


def _usage_from_volume(context, volume_ref, **kw):
    def null_safe_str(s):
        return str(s) if s else ''

    usage_info = dict(
          tenant_id=volume_ref['project_id'],
          user_id=volume_ref['user_id'],
          volume_id=volume_ref['id'],
          volume_type=volume_ref['volume_type'],
          display_name=volume_ref['display_name'],
          launched_at=null_safe_str(volume_ref['launched_at']),
          created_at=null_safe_str(volume_ref['created_at']),
          status=volume_ref['status'],
          snapshot_id=volume_ref['snapshot_id'],
          size=volume_ref['size'])

    usage_info.update(kw)
    return usage_info


def notify_about_volume_usage(context, volume, event_suffix,
                                extra_usage_info=None, host=None):
    if not host:
        host = FLAGS.host

    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = _usage_from_volume(
            context, volume, **extra_usage_info)

    notifier_api.notify(context, 'volume.%s' % host,
                        'volume.%s' % event_suffix,
                        notifier_api.INFO, usage_info)
