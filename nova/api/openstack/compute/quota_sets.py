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

from urllib import parse as urlparse

from oslo_utils import strutils
import webob

from nova.api.openstack import api_version_request
from nova.api.openstack.compute.schemas import quota_sets as schema
from nova.api.openstack import identity
from nova.api.openstack import wsgi
from nova.api import validation
import nova.conf
from nova import exception
from nova.i18n import _
from nova.limit import utils as limit_utils
from nova import objects
from nova.policies import quota_sets as qs_policies
from nova import quota

CONF = nova.conf.CONF
QUOTAS = quota.QUOTAS

FILTERED_QUOTAS_v236 = [
    'fixed_ips', 'floating_ips', 'security_group_rules', 'security_groups'
]

FILTERED_QUOTAS_v257 = list(FILTERED_QUOTAS_v236)
FILTERED_QUOTAS_v257.extend([
    'injected_files',
    'injected_file_content_bytes',
    'injected_file_path_bytes'
])


@validation.validated
class QuotaSetsController(wsgi.Controller):

    def _format_quota_set(self, project_id, quota_set, filtered_quotas):
        """Convert the quota object to a result dict."""
        result = {}
        if project_id:
            result['id'] = str(project_id)

        for resource in QUOTAS.resources:
            if resource not in filtered_quotas and resource in quota_set:
                result[resource] = quota_set[resource]

        return {'quota_set': result}

    def _validate_quota_limit(self, resource, limit, minimum, maximum):
        def conv_inf(value):
            return float("inf") if value == -1 else value

        if conv_inf(limit) < conv_inf(minimum):
            msg = (_("Quota limit %(limit)s for %(resource)s must "
                     "be greater than or equal to already used and "
                     "reserved %(minimum)s.") %
                   {'limit': limit, 'resource': resource, 'minimum': minimum})
            raise webob.exc.HTTPBadRequest(explanation=msg)

        if conv_inf(limit) > conv_inf(maximum):
            msg = (_("Quota limit %(limit)s for %(resource)s must be "
                     "less than or equal to %(maximum)s.") %
                   {'limit': limit, 'resource': resource, 'maximum': maximum})
            raise webob.exc.HTTPBadRequest(explanation=msg)

    def _get_quotas(self, context, id, user_id=None, usages=False):
        if user_id:
            values = QUOTAS.get_user_quotas(context, id, user_id,
                                            usages=usages)
        else:
            values = QUOTAS.get_project_quotas(context, id, usages=usages)

        if usages:
            # NOTE(melwitt): For the detailed quota view with usages, the API
            # returns a response in the format:
            # {
            #     "quota_set": {
            #         "cores": {
            #             "in_use": 0,
            #             "limit": 20,
            #             "reserved": 0
            #         },
            # ...
            # We've re-architected quotas to eliminate reservations, so we no
            # longer have a 'reserved' key returned from get_*_quotas, so set
            # it here to satisfy the REST API response contract.
            reserved = QUOTAS.get_reserved()
            for v in values.values():
                v['reserved'] = reserved
            return values
        else:
            return {k: v['limit'] for k, v in values.items()}

    def _get_filtered_quotas(self, req):
        if api_version_request.is_supported(req, '2.57'):
            return FILTERED_QUOTAS_v257
        elif api_version_request.is_supported(req, '2.36'):
            return FILTERED_QUOTAS_v236
        else:
            return []

    @wsgi.expected_errors(400)
    @validation.query_schema(schema.show_query, '2.0', '2.74')
    @validation.query_schema(schema.show_query_v275, '2.75')
    @validation.response_body_schema(schema.show_response, '2.0', '2.35')
    @validation.response_body_schema(schema.show_response_v236, '2.36', '2.56')
    @validation.response_body_schema(schema.show_response_v257, '2.57')
    def show(self, req, id):
        context = req.environ['nova.context']
        context.can(qs_policies.POLICY_ROOT % 'show', {'project_id': id})
        identity.verify_project_id(context, id)

        params = urlparse.parse_qs(req.environ.get('QUERY_STRING', ''))
        user_id = params.get('user_id', [None])[0]
        filtered_quotas = self._get_filtered_quotas(req)
        return self._format_quota_set(
            id,
            self._get_quotas(context, id, user_id=user_id),
            filtered_quotas=filtered_quotas)

    @wsgi.expected_errors(400)
    @validation.query_schema(schema.detail_query, '2.0', '2.74')
    @validation.query_schema(schema.detail_query_v275, '2.75')
    @validation.response_body_schema(schema.detail_response, '2.0', '2.35')
    @validation.response_body_schema(schema.detail_response_v236, '2.36', '2.56')  # noqa: E501
    @validation.response_body_schema(schema.detail_response_v257, '2.57')
    def detail(self, req, id):
        context = req.environ['nova.context']
        context.can(qs_policies.POLICY_ROOT % 'detail', {'project_id': id})
        identity.verify_project_id(context, id)

        user_id = req.GET.get('user_id', None)
        filtered_quotas = self._get_filtered_quotas(req)
        return self._format_quota_set(
            id,
            self._get_quotas(context, id, user_id=user_id, usages=True),
            filtered_quotas=filtered_quotas)

    @wsgi.expected_errors(400)
    @validation.schema(schema.update, '2.0', '2.35')
    @validation.schema(schema.update_v236, '2.36', '2.56')
    @validation.schema(schema.update_v257, '2.57')
    @validation.query_schema(schema.update_query, '2.0', '2.74')
    @validation.query_schema(schema.update_query_v275, '2.75')
    @validation.response_body_schema(schema.update_response, '2.0', '2.35')
    @validation.response_body_schema(schema.update_response_v236, '2.36', '2.56')  # noqa: E501
    @validation.response_body_schema(schema.update_response_v257, '2.57')
    def update(self, req, id, body):
        context = req.environ['nova.context']
        context.can(qs_policies.POLICY_ROOT % 'update', {'project_id': id})
        identity.verify_project_id(context, id)

        project_id = id
        params = urlparse.parse_qs(req.environ.get('QUERY_STRING', ''))
        user_id = params.get('user_id', [None])[0]
        filtered_quotas = self._get_filtered_quotas(req)

        quota_set = body['quota_set']

        # NOTE(stephenfin): network quotas were only used by nova-network and
        # therefore should be explicitly rejected
        if 'networks' in quota_set:
            raise webob.exc.HTTPBadRequest(
                explanation=_('The networks quota has been removed'))

        force_update = strutils.bool_from_string(quota_set.get('force',
                                                               'False'))
        settable_quotas = QUOTAS.get_settable_quotas(context, project_id,
                                                     user_id=user_id)

        requested_quotas = body['quota_set'].items()
        if limit_utils.use_unified_limits():
            # NOTE(johngarbutt) currently all info comes from keystone
            # we don't update the database.
            requested_quotas = []

        # NOTE(dims): Pass #1 - In this loop for quota_set.items(), we validate
        # min/max values and bail out if any of the items in the set is bad.
        valid_quotas = {}
        for key, value in requested_quotas:
            if key == 'force' or (not value and value != 0):
                continue
            # validate whether already used and reserved exceeds the new
            # quota, this check will be ignored if admin want to force
            # update
            value = int(value)
            if not force_update:
                minimum = settable_quotas[key]['minimum']
                maximum = settable_quotas[key]['maximum']
                self._validate_quota_limit(key, value, minimum, maximum)
            valid_quotas[key] = value

        # NOTE(dims): Pass #2 - At this point we know that all the
        # values are correct and we can iterate and update them all in one
        # shot without having to worry about rolling back etc as we have done
        # the validation up front in the loop above.
        for key, value in valid_quotas.items():
            try:
                objects.Quotas.create_limit(context, project_id,
                                            key, value, user_id=user_id)
            except exception.QuotaExists:
                objects.Quotas.update_limit(context, project_id,
                                            key, value, user_id=user_id)
        # Note(gmann): Removed 'id' from update's response to make it same
        # as V2. If needed it can be added with microversion.
        return self._format_quota_set(
            None,
            self._get_quotas(context, id, user_id=user_id),
            filtered_quotas=filtered_quotas)

    @wsgi.api_version('2.0')
    @wsgi.expected_errors(400)
    @validation.query_schema(schema.defaults_query)
    @validation.response_body_schema(schema.defaults_response, '2.0', '2.35')
    @validation.response_body_schema(schema.defaults_response_v236, '2.36', '2.56')  # noqa: E501
    @validation.response_body_schema(schema.defaults_response_v257, '2.57')
    def defaults(self, req, id):
        context = req.environ['nova.context']
        context.can(qs_policies.POLICY_ROOT % 'defaults', {'project_id': id})
        identity.verify_project_id(context, id)

        values = QUOTAS.get_defaults(context)
        filtered_quotas = self._get_filtered_quotas(req)
        return self._format_quota_set(
            id, values, filtered_quotas=filtered_quotas)

    # TODO(oomichi): Here should be 204(No Content) instead of 202 by v2.1
    # +microversions because the resource quota-set has been deleted completely
    # when returning a response.
    @wsgi.expected_errors(())
    @wsgi.response(202)
    @validation.query_schema(schema.delete_query, '2.0', '2.74')
    @validation.query_schema(schema.delete_query_v275, '2.75')
    @validation.response_body_schema(schema.delete_response)
    def delete(self, req, id):
        context = req.environ['nova.context']
        context.can(qs_policies.POLICY_ROOT % 'delete', {'project_id': id})
        params = urlparse.parse_qs(req.environ.get('QUERY_STRING', ''))
        user_id = params.get('user_id', [None])[0]

        # NOTE(johngarbutt) with unified limits we only use keystone, not the
        # db
        if not limit_utils.use_unified_limits():
            if user_id:
                objects.Quotas.destroy_all_by_project_and_user(
                    context, id, user_id)
            else:
                objects.Quotas.destroy_all_by_project(context, id)
