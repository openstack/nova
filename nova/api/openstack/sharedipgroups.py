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

from nova import wsgi


class Controller(wsgi.Controller):
    """ The Shared IP Groups Controller for the Openstack API """

    def index(self, req):
        raise NotImplementedError

    def show(self, req, id):
        raise NotImplementedError

    def update(self, req, id):
        raise NotImplementedError

    def delete(self, req, id):
        raise NotImplementedError
        
    def detail(self, req):
        raise NotImplementedError

    def create(self, req):
        raise NotImplementedError
