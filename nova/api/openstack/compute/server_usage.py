#   Copyright 2013 OpenStack Foundation
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

from nova.api.openstack import wsgi
from nova.policies import server_usage as su_policies


resp_topic = "OS-SRV-USG"


class ServerUsageController(wsgi.Controller):

    def _extend_server(self, server, instance):
        for k in ['launched_at', 'terminated_at']:
            key = "%s:%s" % (resp_topic, k)
            # NOTE(danms): Historically, this timestamp has been generated
            # merely by grabbing str(datetime) of a TZ-naive object. The
            # only way we can keep that with instance objects is to strip
            # the tzinfo from the stamp and str() it.
            server[key] = (instance[k].replace(tzinfo=None)
                           if instance[k] else None)

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if context.can(su_policies.BASE_POLICY_NAME, fatal=False):
            server = resp_obj.obj['server']
            db_instance = req.get_db_instance(server['id'])
            # server['id'] is guaranteed to be in the cache due to
            # the core API adding it in its 'show' method.
            self._extend_server(server, db_instance)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if context.can(su_policies.BASE_POLICY_NAME, fatal=False):
            servers = list(resp_obj.obj['servers'])
            for server in servers:
                db_instance = req.get_db_instance(server['id'])
                # server['id'] is guaranteed to be in the cache due to
                # the core API adding it in its 'detail' method.
                self._extend_server(server, db_instance)
