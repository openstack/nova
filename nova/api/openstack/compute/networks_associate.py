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

from nova.api.openstack.compute.schemas import networks_associate as schema
from nova.api.openstack import wsgi
from nova.api import validation


_removal_reason = """\
This action only works with *nova-network*, which was deprecated in the
14.0.0 (Newton) release.
It fails with HTTP 404 starting from microversion 2.36.
It was removed in the 21.0.0 (Ussuri) release.
"""


class NetworkAssociateActionController(wsgi.Controller):
    """Network Association API Controller."""

    @wsgi.action("disassociate_host")
    @wsgi.expected_errors(410)
    @wsgi.removed('18.0.0', _removal_reason)
    @validation.schema(schema.disassociate)
    def _disassociate_host_only(self, req, id, body):
        raise exc.HTTPGone()

    @wsgi.action("disassociate_project")
    @wsgi.expected_errors(410)
    @wsgi.removed('18.0.0', _removal_reason)
    @validation.schema(schema.disassociate_project)
    def _disassociate_project_only(self, req, id, body):
        raise exc.HTTPGone()

    @wsgi.action("associate_host")
    @wsgi.expected_errors(410)
    @wsgi.removed('18.0.0', _removal_reason)
    @validation.schema(schema.associate_host)
    def _associate_host(self, req, id, body):
        raise exc.HTTPGone()
