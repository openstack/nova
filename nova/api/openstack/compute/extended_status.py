#   Copyright 2011 OpenStack Foundation
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

"""The Extended Status Admin API extension."""

from nova.api.openstack import wsgi
from nova.policies import extended_status as es_policies


class ExtendedStatusController(wsgi.Controller):
    def _extend_server(self, server, instance):
        # Note(gmann): Removed 'locked_by' from extended status
        # to make it same as V2. If needed it can be added with
        # microversion.
        for state in ['task_state', 'vm_state', 'power_state']:
            # NOTE(mriedem): The OS-EXT-STS prefix should not be used for new
            # attributes after v2.1. They are only in v2.1 for backward compat
            # with v2.0.
            key = "%s:%s" % ('OS-EXT-STS', state)
            server[key] = instance[state]

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if context.can(es_policies.BASE_POLICY_NAME, fatal=False):
            server = resp_obj.obj['server']
            db_instance = req.get_db_instance(server['id'])
            # server['id'] is guaranteed to be in the cache due to
            # the core API adding it in its 'show' method.
            self._extend_server(server, db_instance)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if context.can(es_policies.BASE_POLICY_NAME, fatal=False):
            servers = list(resp_obj.obj['servers'])
            for server in servers:
                db_instance = req.get_db_instance(server['id'])
                # server['id'] is guaranteed to be in the cache due to
                # the core API adding it in its 'detail' method.
                self._extend_server(server, db_instance)
