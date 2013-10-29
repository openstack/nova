# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 OpenStack Foundation
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
"""
Attach open standard audit information to request.environ

AuditMiddleware filter should be place after Keystone's auth_token middleware
in the pipeline so that it can utilise the information Keystone provides.

"""
from pycadf.audit import api as cadf_api

from nova.openstack.common.middleware import notifier


class AuditMiddleware(notifier.RequestNotifier):

    def __init__(self, app, **conf):
        super(AuditMiddleware, self).__init__(app, **conf)
        self.cadf_audit = cadf_api.OpenStackAuditApi()

    @notifier.log_and_ignore_error
    def process_request(self, request):
        self.cadf_audit.append_audit_event(request)
        super(AuditMiddleware, self).process_request(request)

    @notifier.log_and_ignore_error
    def process_response(self, request, response,
                         exception=None, traceback=None):
        self.cadf_audit.mod_audit_event(request, response)
        super(AuditMiddleware, self).process_response(request, response,
                                                      exception, traceback)
