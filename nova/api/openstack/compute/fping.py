# Copyright 2011 Grid Dynamics
# Copyright 2011 OpenStack Foundation
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

import itertools
import os


from webob import exc

from nova.api.openstack.api_version_request \
    import MAX_PROXY_API_SUPPORT_VERSION
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import fping as schema
from nova.api.openstack import wsgi
from nova.api import validation
from nova import compute
import nova.conf
from nova.i18n import _
from nova.policies import fping as fping_policies
from nova import utils

CONF = nova.conf.CONF


class FpingController(wsgi.Controller):

    def __init__(self, network_api=None):
        self.compute_api = compute.API()
        self.last_call = {}

    def check_fping(self):
        if not os.access(CONF.api.fping_path, os.X_OK):
            raise exc.HTTPServiceUnavailable(
                explanation=_("fping utility is not found."))

    @staticmethod
    def fping(ips):
        fping_ret = utils.execute(CONF.api.fping_path, *ips,
                                  check_exit_code=False)
        if not fping_ret:
            return set()
        alive_ips = set()
        for line in fping_ret[0].split("\n"):
            ip = line.split(" ", 1)[0]
            if "alive" in line:
                alive_ips.add(ip)
        return alive_ips

    @staticmethod
    def _get_instance_ips(context, instance):
        ret = []
        for network in common.get_networks_for_instance(
                context, instance).values():
            all_ips = itertools.chain(network["ips"], network["floating_ips"])
            ret += [ip["address"] for ip in all_ips]
        return ret

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @validation.query_schema(schema.index_query)
    @wsgi.expected_errors(503)
    def index(self, req):
        context = req.environ["nova.context"]
        search_opts = dict(deleted=False)
        if "all_tenants" in req.GET:
            context.can(fping_policies.POLICY_ROOT % 'all_tenants')
        else:
            context.can(fping_policies.BASE_POLICY_NAME)
            if context.project_id:
                search_opts["project_id"] = context.project_id
            else:
                search_opts["user_id"] = context.user_id
        self.check_fping()
        include = req.GET.get("include", None)
        if include:
            include = set(include.split(","))
            exclude = set()
        else:
            include = None
            exclude = req.GET.get("exclude", None)
            if exclude:
                exclude = set(exclude.split(","))
            else:
                exclude = set()

        instance_list = self.compute_api.get_all(
            context, search_opts=search_opts)
        ip_list = []
        instance_ips = {}
        instance_projects = {}

        for instance in instance_list:
            uuid = instance.uuid
            if uuid in exclude or (include is not None and
                                   uuid not in include):
                continue
            ips = [str(ip) for ip in self._get_instance_ips(context, instance)]
            instance_ips[uuid] = ips
            instance_projects[uuid] = instance.project_id
            ip_list += ips
        alive_ips = self.fping(ip_list)
        res = []
        for instance_uuid, ips in instance_ips.items():
            res.append({
                "id": instance_uuid,
                "project_id": instance_projects[instance_uuid],
                "alive": bool(set(ips) & alive_ips),
            })
        return {"servers": res}

    @wsgi.Controller.api_version("2.1", MAX_PROXY_API_SUPPORT_VERSION)
    @wsgi.expected_errors((404, 503))
    def show(self, req, id):
        context = req.environ["nova.context"]
        context.can(fping_policies.BASE_POLICY_NAME)
        self.check_fping()
        instance = common.get_instance(self.compute_api, context, id)
        ips = [str(ip) for ip in self._get_instance_ips(context, instance)]
        alive_ips = self.fping(ips)
        return {
            "server": {
                "id": instance.uuid,
                "project_id": instance.project_id,
                "alive": bool(set(ips) & alive_ips),
            }
        }
