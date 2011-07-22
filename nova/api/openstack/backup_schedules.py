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

from nova.api.openstack import wsgi


def _translate_keys(inst):
    """ Coerces the backup schedule into proper dictionary format """
    return dict(backupSchedule=inst)


class Controller(object):
    """ The backup schedule API controller for the Openstack API """

    def __init__(self):
        pass

    def index(self, req, server_id, **kwargs):
        """ Returns the list of backup schedules for a given instance """
        raise exc.HTTPNotImplemented()

    def show(self, req, server_id, id, **kwargs):
        """ Returns a single backup schedule for a given instance """
        raise exc.HTTPNotImplemented()

    def create(self, req, server_id, **kwargs):
        """ No actual update method required, since the existing API allows
        both create and update through a POST """
        raise exc.HTTPNotImplemented()

    def delete(self, req, server_id, id, **kwargs):
        """ Deletes an existing backup schedule """
        raise exc.HTTPNotImplemented()


def create_resource():
    metadata = {
        'attributes': {
            'backupSchedule': [],
        },
    }

    body_serializers = {
        'application/xml': wsgi.XMLDictSerializer(xmlns=wsgi.XMLNS_V10,
                                                  metadata=metadata),
    }

    serializer = wsgi.ResponseSerializer(body_serializers)
    return wsgi.Resource(Controller(), serializer=serializer)
