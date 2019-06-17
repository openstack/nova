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

from nova.api.openstack.compute.schemas import quota_classes
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
FILTERED_QUOTAS_2_50 = ["fixed_ips", "floating_ips", "networks",
                        "security_group_rules", "security_groups"]

# Microversion 2.57 removes personality (injected) files from the API.
FILTERED_QUOTAS_2_57 = list(FILTERED_QUOTAS_2_50)
FILTERED_QUOTAS_2_57.extend(['injected_files', 'injected_file_content_bytes',
                             'injected_file_path_bytes'])


class QuotaClassSetsController(wsgi.Controller):

    supported_quotas = []

    def __init__(self):
        super(QuotaClassSetsController, self).__init__()
        self.supported_quotas = QUOTAS.resources

    def _format_quota_set(self, quota_class, quota_set, filtered_quotas=None,
                          exclude_server_groups=False):
        """Convert the quota object to a result dict."""

        if quota_class:
            result = dict(id=str(quota_class))
        else:
            result = {}
        original_quotas = copy.deepcopy(self.supported_quotas)
        if filtered_quotas:
            original_quotas = [resource for resource in original_quotas
                               if resource not in filtered_quotas]
        # NOTE(gmann): Before microversion v2.50, v2.1 API does not return the
        # 'server_groups' & 'server_group_members' key in quota class API
        # response.
        if exclude_server_groups:
            for resource in EXTENDED_QUOTAS:
                original_quotas.remove(resource)
        for resource in original_quotas:
            if resource in quota_set:
                result[resource] = quota_set[resource]

        return dict(quota_class_set=result)

    @wsgi.Controller.api_version('2.1', '2.49')
    @wsgi.expected_errors(())
    def show(self, req, id):
        return self._show(req, id, exclude_server_groups=True)

    @wsgi.Controller.api_version('2.50', '2.56')  # noqa
    @wsgi.expected_errors(())
    def show(self, req, id):
        return self._show(req, id, FILTERED_QUOTAS_2_50)

    @wsgi.Controller.api_version('2.57')  # noqa
    @wsgi.expected_errors(())
    def show(self, req, id):
        return self._show(req, id, FILTERED_QUOTAS_2_57)

    def _show(self, req, id, filtered_quotas=None,
              exclude_server_groups=False):
        context = req.environ['nova.context']
        context.can(qcs_policies.POLICY_ROOT % 'show', {'quota_class': id})
        values = QUOTAS.get_class_quotas(context, id)
        return self._format_quota_set(id, values, filtered_quotas,
                                      exclude_server_groups)

    @wsgi.Controller.api_version("2.1", "2.49")  # noqa
    @wsgi.expected_errors(400)
    @validation.schema(quota_classes.update)
    def update(self, req, id, body):
        return self._update(req, id, body, exclude_server_groups=True)

    @wsgi.Controller.api_version("2.50", "2.56")  # noqa
    @wsgi.expected_errors(400)
    @validation.schema(quota_classes.update_v250)
    def update(self, req, id, body):
        return self._update(req, id, body, FILTERED_QUOTAS_2_50)

    @wsgi.Controller.api_version("2.57")  # noqa
    @wsgi.expected_errors(400)
    @validation.schema(quota_classes.update_v257)
    def update(self, req, id, body):
        return self._update(req, id, body, FILTERED_QUOTAS_2_57)

    def _update(self, req, id, body, filtered_quotas=None,
                exclude_server_groups=False):
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
        return self._format_quota_set(None, values, filtered_quotas,
                                      exclude_server_groups)
