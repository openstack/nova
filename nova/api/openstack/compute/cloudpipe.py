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

from nova.api.openstack import extensions
from nova.api.openstack import wsgi


class CloudpipeController(wsgi.Controller):
    """Handle creating and listing cloudpipe instances."""

    @extensions.expected_errors((410))
    def create(self, req, body):
        """Create a new cloudpipe instance, if none exists.

        Parameters: {cloudpipe: {'project_id': ''}}
        """
        raise exc.HTTPGone()

    @extensions.expected_errors((410))
    def index(self, req):
        """List running cloudpipe instances."""
        raise exc.HTTPGone()

    @extensions.expected_errors(410)
    def update(self, req, id, body):
        """Configure cloudpipe parameters for the project."""
        raise exc.HTTPGone()
