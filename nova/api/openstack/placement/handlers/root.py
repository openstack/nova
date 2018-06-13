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
"""Handler for the root of the Placement API."""

from oslo_serialization import jsonutils
from oslo_utils import encodeutils
from oslo_utils import timeutils


from nova.api.openstack.placement import microversion
from nova.api.openstack.placement import wsgi_wrapper


@wsgi_wrapper.PlacementWsgify
def home(req):
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]
    min_version = microversion.min_version_string()
    max_version = microversion.max_version_string()
    # NOTE(cdent): As sections of the api are added, links can be
    # added to this output to align with the guidelines at
    # http://specs.openstack.org/openstack/api-wg/guidelines/microversion_specification.html#version-discovery
    version_data = {
        'id': 'v%s' % min_version,
        'max_version': max_version,
        'min_version': min_version,
        # for now there is only ever one version, so it must be CURRENT
        'status': 'CURRENT',
        'links': [{
            # Point back to this same URL as the root of this version.
            # NOTE(cdent): We explicitly want this to be a relative-URL
            # representation of "this same URL", otherwise placement needs
            # to keep track of proxy addresses and the like, which we have
            # avoided thus far, in order to construct full URLs. Placement
            # is much easier to scale if we never track that stuff.
            'rel': 'self',
            'href': '',
        }],
    }
    version_json = jsonutils.dumps({'versions': [version_data]})
    req.response.body = encodeutils.to_utf8(version_json)
    req.response.content_type = 'application/json'
    if want_version.matches((1, 15)):
        req.response.cache_control = 'no-cache'
        req.response.last_modified = timeutils.utcnow(with_timezone=True)
    return req.response
