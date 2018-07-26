# Copyright 2011 Andrew Bogott for the Wikimedia Foundation
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

from nova.api.openstack import wsgi


class FloatingIPDNSDomainController(wsgi.Controller):
    """DNS domain controller for OpenStack API."""

    @wsgi.expected_errors(410)
    def index(self, req):
        raise exc.HTTPGone()

    @wsgi.expected_errors(410)
    def update(self, req, id, body):
        raise exc.HTTPGone()

    @wsgi.expected_errors(410)
    def delete(self, req, id):
        raise exc.HTTPGone()


class FloatingIPDNSEntryController(wsgi.Controller):
    """DNS Entry controller for OpenStack API."""

    @wsgi.expected_errors(410)
    def show(self, req, domain_id, id):
        raise exc.HTTPGone()

    @wsgi.expected_errors(410)
    def update(self, req, domain_id, id, body):
        raise exc.HTTPGone()

    @wsgi.expected_errors(410)
    def delete(self, req, domain_id, id):
        raise exc.HTTPGone()
