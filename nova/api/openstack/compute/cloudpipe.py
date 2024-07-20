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

"""Connect your vlan to the world."""

from webob import exc

from nova.api.openstack.compute.schemas import cloudpipe as schema
from nova.api.openstack import wsgi
from nova.api import validation

_removal_reason = """\
This API only works with *nova-network*, which was deprecated in the
14.0.0 (Newton) release.
It was removed in the 16.0.0 (Pike) release.
"""


class CloudpipeController(wsgi.Controller):
    """Handle creating and listing cloudpipe instances."""

    @wsgi.expected_errors((410))
    @wsgi.removed('16.0.0', _removal_reason)
    @validation.schema(schema.create)
    def create(self, req, body):
        """Create a new cloudpipe instance, if none exists."""
        raise exc.HTTPGone()

    @wsgi.expected_errors((410))
    @wsgi.removed('16.0.0', _removal_reason)
    @validation.query_schema(schema.index_query)
    def index(self, req):
        """List running cloudpipe instances."""
        raise exc.HTTPGone()

    @wsgi.expected_errors(410)
    @wsgi.removed('16.0.0', _removal_reason)
    @validation.schema(schema.update)
    def update(self, req, id, body):
        """Configure cloudpipe parameters for the project."""
        raise exc.HTTPGone()
