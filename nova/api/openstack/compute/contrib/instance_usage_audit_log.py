# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC.
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
from webob import exc

from nova.api.openstack import extensions
from nova.compute import utils as compute_utils
from nova import context as nova_context
from nova import exception
from nova import flags

FLAGS = flags.FLAGS


authorize = extensions.extension_authorizer('compute',
                           'instance_usage_audit_log')


class InstanceUsageAuditLogController(object):

    def index(self, req):
        context = req.environ['nova.context']
        authorize(context)
        task_log = compute_utils.get_audit_task_logs(context)
        return {'instance_usage_audit_logs': task_log}

    def show(self, req, id):
        context = req.environ['nova.context']
        authorize(context)
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
        task_log = compute_utils.get_audit_task_logs(context,
                                                     before=before_date)
        return {'instance_usage_audit_log': task_log}


class Instance_usage_audit_log(extensions.ExtensionDescriptor):
    """Admin-only Task Log Monitoring"""
    name = "OSInstanceUsageAuditLog"
    alias = "os-instance_usage_audit_log"
    namespace = "http://docs.openstack.org/ext/services/api/v1.1"
    updated = "2012-07-06T01:00:00+00:00"

    def get_resources(self):
        ext = extensions.ResourceExtension('os-instance_usage_audit_log',
                                           InstanceUsageAuditLogController())
        return [ext]
