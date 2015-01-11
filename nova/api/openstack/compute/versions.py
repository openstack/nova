# Copyright 2011 OpenStack Foundation
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

from oslo_config import cfg

from nova.api.openstack.compute.views import versions as views_versions
from nova.api.openstack import wsgi


CONF = cfg.CONF
CONF.import_opt('enabled', 'nova.api.openstack', group='osapi_v3')

LINKS = {
   'v2.0': {
       'html': 'http://docs.openstack.org/'
    },
   'v2.1': {
       'html': 'http://docs.openstack.org/'
    },
}


VERSIONS = {
    "v2.0": {
        "id": "v2.0",
        "status": "CURRENT",
        "updated": "2011-01-21T11:33:21Z",
        "links": [
            {
                "rel": "describedby",
                "type": "text/html",
                "href": LINKS['v2.0']['html'],
            },
        ],
        "media-types": [
            {
                "base": "application/json",
                "type": "application/vnd.openstack.compute+json;version=2",
            }
        ],
    },
    "v2.1": {
        "id": "v2.1",
        "status": "EXPERIMENTAL",
        "updated": "2013-07-23T11:33:21Z",
        "links": [
            {
                "rel": "describedby",
                "type": "text/html",
                "href": LINKS['v2.1']['html'],
            },
        ],
        "media-types": [
            {
                "base": "application/json",
                "type": "application/vnd.openstack.compute+json;version=2.1",
            }
        ],
    }
}


class Versions(wsgi.Resource):
    def __init__(self):
        super(Versions, self).__init__(None)
        if not CONF.osapi_v3.enabled:
            del VERSIONS["v2.1"]

    def index(self, req, body=None):
        """Return all versions."""
        builder = views_versions.get_view_builder(req)
        return builder.build_versions(VERSIONS)

    @wsgi.response(300)
    def multi(self, req, body=None):
        """Return multiple choices."""
        builder = views_versions.get_view_builder(req)
        return builder.build_choices(VERSIONS, req)

    def get_action_args(self, request_environment):
        """Parse dictionary created by routes library."""
        args = {}
        if request_environment['PATH_INFO'] == '/':
            args['action'] = 'index'
        else:
            args['action'] = 'multi'

        return args


class VersionV2(object):
    def show(self, req):
        builder = views_versions.get_view_builder(req)
        return builder.build_version(VERSIONS['v2.0'])


def create_resource():
    return wsgi.Resource(VersionV2())
