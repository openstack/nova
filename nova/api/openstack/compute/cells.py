# Copyright 2011-2012 OpenStack Foundation
# All Rights Reserved.
# Copyright 2013 Red Hat, Inc.
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

from nova.api.openstack.compute.schemas import cells as schema
from nova.api.openstack import wsgi
from nova.api import validation

_removal_reason = """\
This API only works in a Cells v1 deployment, which was deprecated in the
16.0.0 (Pike) release. It is not used with Cells v2, which is required
beginning in the 15.0.0 (Ocata) release.
It was removed in the 20.0.0 (Train) release.
"""


class CellsController(wsgi.Controller):
    """(Removed) Controller for Cell resources.

    This was removed during the Train release in favour of cells v2.
    """

    @wsgi.expected_errors(410)
    @wsgi.removed('20.0.0', _removal_reason)
    @validation.query_schema(schema.index_query)
    def index(self, req):
        raise exc.HTTPGone()

    @wsgi.expected_errors(410)
    @wsgi.removed('20.0.0', _removal_reason)
    @validation.query_schema(schema.detail_query)
    def detail(self, req):
        raise exc.HTTPGone()

    @wsgi.expected_errors(410)
    @wsgi.removed('20.0.0', _removal_reason)
    @validation.query_schema(schema.info_query)
    def info(self, req):
        raise exc.HTTPGone()

    @wsgi.expected_errors(410)
    @wsgi.removed('20.0.0', _removal_reason)
    @validation.query_schema(schema.capacities_query)
    def capacities(self, req, id=None):
        raise exc.HTTPGone()

    @wsgi.expected_errors(410)
    @wsgi.removed('20.0.0', _removal_reason)
    @validation.query_schema(schema.show_query)
    def show(self, req, id):
        raise exc.HTTPGone()

    @wsgi.expected_errors(410)
    @wsgi.removed('20.0.0', _removal_reason)
    def delete(self, req, id):
        raise exc.HTTPGone()

    @wsgi.expected_errors(410)
    @wsgi.removed('20.0.0', _removal_reason)
    @validation.schema(schema.create)
    def create(self, req, body):
        raise exc.HTTPGone()

    @wsgi.expected_errors(410)
    @wsgi.removed('20.0.0', _removal_reason)
    @validation.schema(schema.update)
    def update(self, req, id, body):
        raise exc.HTTPGone()

    @wsgi.expected_errors(410)
    @wsgi.removed('20.0.0', _removal_reason)
    @validation.schema(schema.sync_instances)
    def sync_instances(self, req, body):
        raise exc.HTTPGone()
