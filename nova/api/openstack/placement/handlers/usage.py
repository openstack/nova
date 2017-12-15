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
from oslo_utils import timeutils
import webob

from nova.api.openstack.placement import microversion
from nova.api.openstack.placement.schemas import usage as schema
from nova.api.openstack.placement import util
from nova.api.openstack.placement import wsgi_wrapper
from nova import exception
from nova.i18n import _
from nova.objects import resource_provider as rp_obj


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
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]

    # Resource provider object needed for two things: If it is
    # NotFound we'll get a 404 here, which needs to happen because
    # get_all_by_resource_provider_uuid can return an empty list.
    # It is also needed for the generation, used in the outgoing
    # representation.
    try:
        resource_provider = rp_obj.ResourceProvider.get_by_uuid(
            context, uuid)
    except exception.NotFound as exc:
        raise webob.exc.HTTPNotFound(
            _("No resource provider with uuid %(uuid)s found: %(error)s") %
             {'uuid': uuid, 'error': exc})

    usage = rp_obj.UsageList.get_all_by_resource_provider_uuid(
        context, uuid)

    response = req.response
    response.body = encodeutils.to_utf8(jsonutils.dumps(
        _serialize_usages(resource_provider, usage)))
    req.response.content_type = 'application/json'
    if want_version.matches((1, 15)):
        req.response.cache_control = 'no-cache'
        # While it would be possible to generate a last-modified time
        # based on the collection of allocations that result in a usage
        # value (with some spelunking in the SQL) that doesn't align with
        # the question that is being asked in a request for usages: What
        # is the usage, now? So the last-modified time is set to utcnow.
        req.response.last_modified = timeutils.utcnow(with_timezone=True)
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
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]

    util.validate_query_params(req, schema.GET_USAGES_SCHEMA_1_9)

    project_id = req.GET.get('project_id')
    user_id = req.GET.get('user_id')

    usages = rp_obj.UsageList.get_all_by_project_user(context, project_id,
                                                      user_id=user_id)

    response = req.response
    usages_dict = {'usages': {resource.resource_class: resource.usage
                   for resource in usages}}
    response.body = encodeutils.to_utf8(jsonutils.dumps(usages_dict))
    req.response.content_type = 'application/json'
    if want_version.matches((1, 15)):
        req.response.cache_control = 'no-cache'
        # While it would be possible to generate a last-modified time
        # based on the collection of allocations that result in a usage
        # value (with some spelunking in the SQL) that doesn't align with
        # the question that is being asked in a request for usages: What
        # is the usage, now? So the last-modified time is set to utcnow.
        req.response.last_modified = timeutils.utcnow(with_timezone=True)
    return req.response
