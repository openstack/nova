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


def _translate_keys(inst):
    """ Coerces the backup schedule into proper dictionary format """
    return dict(backupSchedule=inst)


class Controller(wsgi.Controller):
    """ The backup schedule API controller for the Openstack API """

    _serialization_metadata = {
        'application/xml': {
            'attributes': {
                'backupSchedule': []}}}

    def __init__(self):
        pass

    def index(self, req, server_id):
        """ Returns the list of backup schedules for a given instance """
        return faults.Fault(exc.HTTPNotImplemented())

    def show(self, req, server_id, id):
        """ Returns a single backup schedule for a given instance """
        return faults.Fault(exc.HTTPNotImplemented())

    def create(self, req, server_id):
        """ No actual update method required, since the existing API allows
        both create and update through a POST """
        return faults.Fault(exc.HTTPNotImplemented())

    def delete(self, req, server_id, id):
        """ Deletes an existing backup schedule """
        return faults.Fault(exc.HTTPNotImplemented())
