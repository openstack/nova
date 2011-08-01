# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 OpenStack LLC.
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

from nova.api.openstack import wsgi


class Controller(object):
    """ The Shared IP Groups Controller for the Openstack API """

    def index(self, req, **kwargs):
        """ Returns a list of Shared IP Groups for the user """
        raise exc.HTTPNotImplemented()

    def show(self, req, id, **kwargs):
        """ Shows in-depth information on a specific Shared IP Group """
        raise exc.HTTPNotImplemented()

    def update(self, req, id, **kwargs):
        """ You can't update a Shared IP Group """
        raise exc.HTTPNotImplemented()

    def delete(self, req, id, **kwargs):
        """ Deletes a Shared IP Group """
        raise exc.HTTPNotImplemented()

    def detail(self, req, **kwargs):
        """ Returns a complete list of Shared IP Groups """
        raise exc.HTTPNotImplemented()

    def create(self, req, **kwargs):
        """ Creates a new Shared IP group """
        raise exc.HTTPNotImplemented()


def create_resource():
    return wsgi.Resource(Controller())
