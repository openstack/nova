# Copyright 2011 Openstack, LLC
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

"""The deferred instance delete extension."""

import webob

from nova.api.openstack import common
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova import compute
from nova import exception
from nova import log as logging


LOG = logging.getLogger("nova.api.openstack.compute.contrib.deferred-delete")


class DeferredDeleteController(wsgi.Controller):
    def __init__(self, *args, **kwargs):
        super(DeferredDeleteController, self).__init__(*args, **kwargs)
        self.compute_api = compute.API()

    @wsgi.action('restore')
    def _restore(self, req, id, body):
        """Restore a previously deleted instance."""

        context = req.environ["nova.context"]
        instance = self.compute_api.get(context, id)
        try:
            self.compute_api.restore(context, instance)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'restore')
        return webob.Response(status_int=202)

    @wsgi.action('forceDelete')
    def _force_delete(self, req, id, body):
        """Force delete of instance before deferred cleanup."""

        context = req.environ["nova.context"]
        instance = self.compute_api.get(context, id)
        try:
            self.compute_api.force_delete(context, instance)
        except exception.InstanceInvalidState as state_error:
            common.raise_http_conflict_for_instance_invalid_state(state_error,
                    'forceDelete')
        return webob.Response(status_int=202)


class Deferred_delete(extensions.ExtensionDescriptor):
    """Instance deferred delete"""

    name = "DeferredDelete"
    alias = "os-deferred-delete"
    namespace = "http://docs.openstack.org/compute/ext/" \
                "deferred-delete/api/v1.1"
    updated = "2011-09-01T00:00:00+00:00"

    def get_controller_extensions(self):
        controller = DeferredDeleteController()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]
