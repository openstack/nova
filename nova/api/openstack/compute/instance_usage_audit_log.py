# Copyright 2012 OpenStack Foundation
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


import datetime

import webob.exc

from nova.api.openstack import wsgi
from nova.compute import api as compute
from nova.compute import rpcapi as compute_rpcapi
from nova.i18n import _
from nova.policies import instance_usage_audit_log as iual_policies
from nova import utils


class InstanceUsageAuditLogController(wsgi.Controller):

    def __init__(self):
        super(InstanceUsageAuditLogController, self).__init__()
        self.host_api = compute.HostAPI()

    @wsgi.expected_errors(())
    def index(self, req):
        context = req.environ['nova.context']
        context.can(iual_policies.BASE_POLICY_NAME)
        task_log = self._get_audit_task_logs(context)
        return {'instance_usage_audit_logs': task_log}

    @wsgi.expected_errors(400)
    def show(self, req, id):
        context = req.environ['nova.context']
        context.can(iual_policies.BASE_POLICY_NAME)
        try:
            if '.' in id:
                before_date = datetime.datetime.strptime(str(id),
                                                "%Y-%m-%d %H:%M:%S.%f")
            else:
                before_date = datetime.datetime.strptime(str(id),
                                                "%Y-%m-%d %H:%M:%S")
        except ValueError:
            msg = _("Invalid timestamp for date %s") % id
            raise webob.exc.HTTPBadRequest(explanation=msg)
        task_log = self._get_audit_task_logs(context, before=before_date)
        return {'instance_usage_audit_log': task_log}

    def _get_audit_task_logs(self, context, before=None):
        """Returns a full log for all instance usage audit tasks on all
           computes.

        :param context: Nova request context.
        :param before: By default we look for the audit period most recently
            completed before this datetime. Has no effect if both begin and end
            are specified.
        """
        begin, end = utils.last_completed_audit_period(before=before)
        task_logs = self.host_api.task_log_get_all(context,
                                                   "instance_usage_audit",
                                                   begin, end)
        # We do this in this way to include disabled compute services,
        # which can have instances on them. (mdragon)
        filters = {'topic': compute_rpcapi.RPC_TOPIC}
        services = self.host_api.service_get_all(context, filters=filters)
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
        log = {tl['host']: dict(state=tl['state'],
                                instances=tl['task_items'],
                                errors=tl['errors'],
                                message=tl['message'])
               for tl in task_logs}
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
