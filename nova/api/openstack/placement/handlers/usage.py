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
"""Placement API handlers for usage information."""

from oslo_serialization import jsonutils
from oslo_utils import encodeutils
import webob

from nova.api.openstack.placement import microversion
from nova.api.openstack.placement import util
from nova.api.openstack.placement import wsgi_wrapper
from nova import exception
from nova.i18n import _
from nova import objects


# Represents the allowed query string parameters to GET /usages
GET_USAGES_SCHEMA_1_9 = {
    "type": "object",
    "properties": {
        "project_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 255,
        },
        "user_id": {
            "type": "string",
            "minLength": 1,
            "maxLength": 255,
        },
    },
    "required": [
        "project_id"
     ],
    "additionalProperties": False,
}


def _serialize_usages(resource_provider, usage):
    usage_dict = {resource.resource_class: resource.usage
                  for resource in usage}
    return {'resource_provider_generation': resource_provider.generation,
            'usages': usage_dict}


@wsgi_wrapper.PlacementWsgify
@util.check_accept('application/json')
def list_usages(req):
    """GET a dictionary of resource provider usage by resource class.

    If the resource provider does not exist return a 404.

    On success return a 200 with an application/json representation of
    the usage dictionary.
    """
    context = req.environ['placement.context']
    uuid = util.wsgi_path_item(req.environ, 'uuid')

    # Resource provider object needed for two things: If it is
    # NotFound we'll get a 404 here, which needs to happen because
    # get_all_by_resource_provider_uuid can return an empty list.
    # It is also needed for the generation, used in the outgoing
    # representation.
    try:
        resource_provider = objects.ResourceProvider.get_by_uuid(
            context, uuid)
    except exception.NotFound as exc:
        raise webob.exc.HTTPNotFound(
            _("No resource provider with uuid %(uuid)s found: %(error)s") %
             {'uuid': uuid, 'error': exc})

    usage = objects.UsageList.get_all_by_resource_provider_uuid(
        context, uuid)

    response = req.response
    response.body = encodeutils.to_utf8(jsonutils.dumps(
        _serialize_usages(resource_provider, usage)))
    req.response.content_type = 'application/json'
    return req.response


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.9')
@util.check_accept('application/json')
def get_total_usages(req):
    """GET the sum of usages for a project or a project/user.

    On success return a 200 and an application/json body representing the
    sum/total of usages.
    Return 404 Not Found if the wanted microversion does not match.
    """
    context = req.environ['placement.context']

    schema = GET_USAGES_SCHEMA_1_9

    util.validate_query_params(req, schema)

    project_id = req.GET.get('project_id')
    user_id = req.GET.get('user_id')

    usages = objects.UsageList.get_all_by_project_user(context, project_id,
                                                       user_id=user_id)

    response = req.response
    usages_dict = {'usages': {resource.resource_class: resource.usage
                   for resource in usages}}
    response.body = encodeutils.to_utf8(jsonutils.dumps(usages_dict))
    req.response.content_type = 'application/json'
    return req.response
