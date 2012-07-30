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

from nova import db
from nova import exception
from nova import flags
from nova.network import model as network_model
from nova import notifications
from nova.openstack.common import log
from nova.openstack.common.notifier import api as notifier_api
from nova import utils

FLAGS = flags.FLAGS
LOG = log.getLogger(__name__)


def notify_usage_exists(context, instance_ref, current_period=False,
                        ignore_missing_network_data=True,
                        system_metadata=None, extra_usage_info=None):
    """Generates 'exists' notification for an instance for usage auditing
    purposes.

    :param current_period: if True, this will generate a usage for the
        current usage period; if False, this will generate a usage for the
        previous audit period.

    :param ignore_missing_network_data: if True, log any exceptions generated
        while getting network info; if False, raise the exception.
    :param system_metadata: system_metadata DB entries for the instance,
        if not None.  *NOTE*: Currently unused here in trunk, but needed for
        potential custom modifications.
    :param extra_usage_info: Dictionary containing extra values to add or
        override in the notification if not None.
    """

    audit_start, audit_end = notifications.audit_period_bounds(current_period)

    bw = notifications.bandwidth_usage(instance_ref, audit_start,
            ignore_missing_network_data)

    if system_metadata is None:
        try:
            system_metadata = db.instance_system_metadata_get(
                    context, instance_ref['uuid'])
        except exception.NotFound:
            system_metadata = {}

    # add image metadata to the notification:
    image_meta = notifications.image_meta(system_metadata)

    extra_info = dict(audit_period_beginning=str(audit_start),
                      audit_period_ending=str(audit_end),
                      bandwidth=bw, image_meta=image_meta)

    if extra_usage_info:
        extra_info.update(extra_usage_info)

    notify_about_instance_usage(context, instance_ref, 'exists',
            system_metadata=system_metadata, extra_usage_info=extra_info)


def notify_about_instance_usage(context, instance, event_suffix,
                                network_info=None, system_metadata=None,
                                extra_usage_info=None, host=None):
    """
    Send a notification about an instance.

    :param event_suffix: Event type like "delete.start" or "exists"
    :param network_info: Networking information, if provided.
    :param system_metadata: system_metadata DB entries for the instance,
        if provided.
    :param extra_usage_info: Dictionary containing extra values to add or
        override in the notification.
    :param host: Compute host for the instance, if specified.  Default is
        FLAGS.host
    """

    if not host:
        host = FLAGS.host

    if not extra_usage_info:
        extra_usage_info = {}

    usage_info = notifications.info_from_instance(context, instance,
            network_info, system_metadata, **extra_usage_info)

    notifier_api.notify(context, 'compute.%s' % host,
                        'compute.instance.%s' % event_suffix,
                        notifier_api.INFO, usage_info)


def get_nw_info_for_instance(instance):
    info_cache = instance['info_cache'] or {}
    cached_nwinfo = info_cache.get('network_info') or []
    return network_model.NetworkInfo.hydrate(cached_nwinfo)


def has_audit_been_run(context, host, timestamp=None):
    begin, end = utils.last_completed_audit_period(before=timestamp)
    task_log = db.task_log_get(context, "instance_usage_audit",
                               begin, end, host)
    if task_log:
        return True
    else:
        return False


def start_instance_usage_audit(context, begin, end, host, num_instances):
    db.task_log_begin_task(context, "instance_usage_audit", begin, end, host,
                           num_instances, "Instance usage audit started...")


def finish_instance_usage_audit(context, begin, end, host, errors, message):
    db.task_log_end_task(context, "instance_usage_audit", begin, end, host,
                         errors, message)
