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

import time
from webob import exc

from nova import wsgi
from nova.api.openstack import faults
import nova.image.service

class Controller(wsgi.Controller):
    def __init__(self):
        pass

    def index(self, req, server_id):
        return faults.Fault(exc.HTTPNotFound())

    def create(self, req, server_id):
        """ No actual update method required, since the existing API allows
        both create and update through a POST """
        return faults.Fault(exc.HTTPNotFound())

    def delete(self, req, server_id):
        return faults.Fault(exc.HTTPNotFound())
