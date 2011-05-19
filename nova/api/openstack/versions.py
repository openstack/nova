# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

import webob
import webob.dec

from nova import wsgi as base_wsgi
import nova.api.openstack.views.versions
from nova.api.openstack import wsgi


class Versions(wsgi.Resource, base_wsgi.Application):
    def __init__(self):
        metadata = {
            "attributes": {
                "version": ["status", "id"],
                "link": ["rel", "href"],
            }
        }

        serializers = {
            'application/xml': wsgi.XMLSerializer(metadata=metadata),
        }

        super(Versions, self).__init__(None, serializers=serializers)

    def dispatch(self, request, *args):
        """Respond to a request for all OpenStack API versions."""
        version_objs = [
            {
                "id": "v1.1",
                "status": "CURRENT",
            },
            {
                "id": "v1.0",
                "status": "DEPRECATED",
            },
        ]

        builder = nova.api.openstack.views.versions.get_view_builder(request)
        versions = [builder.build(version) for version in version_objs]
        return dict(versions=versions)
