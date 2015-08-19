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

import six
import webob

from nova.api.openstack.compute.schemas import quota_classes
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova import db
from nova import exception
from nova import quota
from nova import utils


QUOTAS = quota.QUOTAS
ALIAS = "os-quota-class-sets"

# Quotas that are only enabled by specific extensions
EXTENDED_QUOTAS = {'server_groups': 'os-server-group-quotas',
                   'server_group_members': 'os-server-group-quotas'}


authorize = extensions.os_compute_authorizer(ALIAS)


class QuotaClassSetsController(wsgi.Controller):

    supported_quotas = []

    def __init__(self, **kwargs):
        self.supported_quotas = QUOTAS.resources
        extension_info = kwargs.pop('extension_info').get_extensions()
        for resource, extension in EXTENDED_QUOTAS.items():
            if extension not in extension_info:
                self.supported_quotas.remove(resource)

    def _format_quota_set(self, quota_class, quota_set):
        """Convert the quota object to a result dict."""

        if quota_class:
            result = dict(id=str(quota_class))
        else:
            result = {}

        for resource in self.supported_quotas:
            if resource in quota_set:
                result[resource] = quota_set[resource]

        return dict(quota_class_set=result)

    @extensions.expected_errors(())
    def show(self, req, id):
        context = req.environ['nova.context']
        authorize(context, action='show', target={'quota_class': id})
        values = QUOTAS.get_class_quotas(context, id)
        return self._format_quota_set(id, values)

    @extensions.expected_errors(400)
    @validation.schema(quota_classes.update)
    def update(self, req, id, body):
        context = req.environ['nova.context']
        authorize(context, action='update', target={'quota_class': id})
        try:
            utils.check_string_length(id, 'quota_class_name',
                                      min_length=1, max_length=255)
        except exception.InvalidInput as e:
            raise webob.exc.HTTPBadRequest(
                explanation=e.format_message())

        quota_class = id

        for key, value in six.iteritems(body['quota_class_set']):
            try:
                db.quota_class_update(context, quota_class, key, value)
            except exception.QuotaClassNotFound:
                db.quota_class_create(context, quota_class, key, value)

        values = QUOTAS.get_class_quotas(context, quota_class)
        return self._format_quota_set(None, values)


class QuotaClasses(extensions.V21APIExtensionBase):
    """Quota classes management support."""

    name = "QuotaClasses"
    alias = ALIAS
    version = 1

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension(
            ALIAS,
            QuotaClassSetsController(extension_info=self.extension_info))
        resources.append(res)
        return resources

    def get_controller_extensions(self):
        return []
