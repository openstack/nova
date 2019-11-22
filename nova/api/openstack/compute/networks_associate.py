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

from nova.api.openstack import wsgi


class NetworkAssociateActionController(wsgi.Controller):
    """Network Association API Controller."""

    @wsgi.action("disassociate_host")
    @wsgi.expected_errors(410)
    def _disassociate_host_only(self, req, id, body):
        raise exc.HTTPGone()

    @wsgi.action("disassociate_project")
    @wsgi.expected_errors(410)
    def _disassociate_project_only(self, req, id, body):
        raise exc.HTTPGone()

    @wsgi.action("associate_host")
    @wsgi.expected_errors(410)
    def _associate_host(self, req, id, body):
        raise exc.HTTPGone()
