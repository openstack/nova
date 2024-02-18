# Copyright 2010 OpenStack Foundation
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

from webob import exc

from nova.api.openstack.compute.schemas import consoles as schema
from nova.api.openstack import wsgi
from nova.api import validation

_removal_reason = """\
This API only works with the Xen virt driver, which was deprecated in the
20.0.0 (Train) release.
It was removed in the 21.0.0 (Ussuri) release.
"""


class ConsolesController(wsgi.Controller):
    """(Removed) The Consoles controller for the OpenStack API.

    This was removed during the Ussuri release along with the nova-console
    service.
    """

    @wsgi.expected_errors(410)
    @wsgi.removed('21.0.0', _removal_reason)
    @validation.query_schema(schema.index_query)
    def index(self, req, server_id):
        raise exc.HTTPGone()

    @wsgi.expected_errors(410)
    @wsgi.removed('21.0.0', _removal_reason)
    @validation.schema(schema.create)
    def create(self, req, server_id, body):
        raise exc.HTTPGone()

    @wsgi.expected_errors(410)
    @wsgi.removed('21.0.0', _removal_reason)
    @validation.query_schema(schema.show_query)
    def show(self, req, server_id, id):
        raise exc.HTTPGone()

    @wsgi.expected_errors(410)
    @wsgi.removed('21.0.0', _removal_reason)
    def delete(self, req, server_id, id):
        raise exc.HTTPGone()
