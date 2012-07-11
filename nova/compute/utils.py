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
                    context, instance_ref.uuid)
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

    usage_info = notifications.usage_from_instance(context, instance,
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


def get_audit_task_logs(context, begin=None, end=None, before=None):
    """Returns a full log for all instance usage audit tasks on all computes.

    :param begin: datetime beginning of audit period to get logs for,
        Defaults to the beginning of the most recently completed
        audit period prior to the 'before' date.
    :param end: datetime ending of audit period to get logs for,
        Defaults to the ending of the most recently completed
        audit period prior to the 'before' date.
    :param before: By default we look for the audit period most recently
        completed before this datetime. Has no effect if both begin and end
        are specified.
    """
    defbegin, defend = utils.last_completed_audit_period(before=before)
    if begin is None:
        begin = defbegin
    if end is None:
        end = defend
    task_logs = db.task_log_get_all(context, "instance_usage_audit",
                                    begin, end)
    services = db.service_get_all_by_topic(context, "compute")
    hosts = set(serv['host'] for serv in services)
    seen_hosts = set()
    done_hosts = set()
    running_hosts = set()
    total_errors = 0
    total_items = 0
    for tlog in task_logs:
        seen_hosts.add(tlog['host'])
        if tlog['state'] == "DONE":
            done_hosts.add(tlog['host'])
        if tlog['state'] == "RUNNING":
            running_hosts.add(tlog['host'])
        total_errors += tlog['errors']
        total_items += tlog['task_items']
    log = dict((tl['host'], dict(state=tl['state'],
                              instances=tl['task_items'],
                              errors=tl['errors'],
                              message=tl['message']))
              for tl in task_logs)
    missing_hosts = hosts - seen_hosts
    overall_status = "%s hosts done. %s errors." % (
                'ALL' if len(done_hosts) == len(hosts)
                else "%s of %s" % (len(done_hosts), len(hosts)),
                total_errors)
    return dict(period_beginning=str(begin),
                period_ending=str(end),
                num_hosts=len(hosts),
                num_hosts_done=len(done_hosts),
                num_hosts_running=len(running_hosts),
                num_hosts_not_run=len(missing_hosts),
                hosts_not_run=list(missing_hosts),
                total_instances=total_items,
                total_errors=total_errors,
                overall_status=overall_status,
                log=log)
