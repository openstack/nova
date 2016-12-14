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

import copy
import webob

from nova.api.openstack import api_version_request
from nova.api.openstack.compute.schemas import quota_classes
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova import exception
from nova import objects
from nova.policies import quota_class_sets as qcs_policies
from nova import quota
from nova import utils


QUOTAS = quota.QUOTAS

# NOTE(gmann): Quotas which were returned in v2 but in v2.1 those
# were not returned. Fixed in microversion 2.50. Bug#1693168.
EXTENDED_QUOTAS = ['server_groups', 'server_group_members']

# NOTE(gmann): Network related quotas are filter out in
# microversion 2.50. Bug#1701211.
FILTERED_QUOTAS = ["fixed_ips", "floating_ips", "networks",
                   "security_group_rules", "security_groups"]


class QuotaClassSetsController(wsgi.Controller):

    supported_quotas = []

    def __init__(self, **kwargs):
        self.supported_quotas = QUOTAS.resources

    def _format_quota_set(self, quota_class, quota_set, req):
        """Convert the quota object to a result dict."""

        if quota_class:
            result = dict(id=str(quota_class))
        else:
            result = {}
        original_quotas = copy.deepcopy(self.supported_quotas)
        if api_version_request.is_supported(req, min_version="2.50"):
            original_quotas = [resource for resource in original_quotas
                               if resource not in FILTERED_QUOTAS]
        # NOTE(gmann): Before microversion v2.50, v2.1 API does not return the
        # 'server_groups' & 'server_group_members' key in quota class API
        # response.
        else:
            for resource in EXTENDED_QUOTAS:
                original_quotas.remove(resource)
        for resource in original_quotas:
            if resource in quota_set:
                result[resource] = quota_set[resource]

        return dict(quota_class_set=result)

    @extensions.expected_errors(())
    def show(self, req, id):
        context = req.environ['nova.context']
        context.can(qcs_policies.POLICY_ROOT % 'show', {'quota_class': id})
        values = QUOTAS.get_class_quotas(context, id)
        return self._format_quota_set(id, values, req)

    @extensions.expected_errors(400)
    @validation.schema(quota_classes.update, "2.0", "2.49")
    @validation.schema(quota_classes.update_v250, "2.50")
    def update(self, req, id, body):
        context = req.environ['nova.context']
        context.can(qcs_policies.POLICY_ROOT % 'update', {'quota_class': id})
        try:
            utils.check_string_length(id, 'quota_class_name',
                                      min_length=1, max_length=255)
        except exception.InvalidInput as e:
            raise webob.exc.HTTPBadRequest(
                explanation=e.format_message())

        quota_class = id

        for key, value in body['quota_class_set'].items():
            try:
                objects.Quotas.update_class(context, quota_class, key, value)
            except exception.QuotaClassNotFound:
                objects.Quotas.create_class(context, quota_class, key, value)

        values = QUOTAS.get_class_quotas(context, quota_class)
        return self._format_quota_set(None, values, req)
