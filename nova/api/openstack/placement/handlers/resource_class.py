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
"""Placement API handlers for resource classes."""

from oslo_serialization import jsonutils
from oslo_utils import encodeutils
from oslo_utils import timeutils
import webob

from nova.api.openstack.placement import exception
from nova.api.openstack.placement import microversion
from nova.api.openstack.placement.objects import resource_provider as rp_obj
from nova.api.openstack.placement.policies import resource_class as policies
from nova.api.openstack.placement.schemas import resource_class as schema
from nova.api.openstack.placement import util
from nova.api.openstack.placement import wsgi_wrapper
from nova.i18n import _


def _serialize_links(environ, rc):
    url = util.resource_class_url(environ, rc)
    links = [{'rel': 'self', 'href': url}]
    return links


def _serialize_resource_class(environ, rc):
    data = {
        'name': rc.name,
        'links': _serialize_links(environ, rc)
    }
    return data


def _serialize_resource_classes(environ, rcs, want_version):
    output = []
    last_modified = None
    get_last_modified = want_version.matches((1, 15))
    for rc in rcs:
        if get_last_modified:
            last_modified = util.pick_last_modified(last_modified, rc)
        data = _serialize_resource_class(environ, rc)
        output.append(data)
    last_modified = last_modified or timeutils.utcnow(with_timezone=True)
    return ({"resource_classes": output}, last_modified)


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.2')
@util.require_content('application/json')
def create_resource_class(req):
    """POST to create a resource class.

    On success return a 201 response with an empty body and a location
    header pointing to the newly created resource class.
    """
    context = req.environ['placement.context']
    context.can(policies.CREATE)
    data = util.extract_json(req.body, schema.POST_RC_SCHEMA_V1_2)

    try:
        rc = rp_obj.ResourceClass(context, name=data['name'])
        rc.create()
    except exception.ResourceClassExists:
        raise webob.exc.HTTPConflict(
            _('Conflicting resource class already exists: %(name)s') %
            {'name': data['name']})
    except exception.MaxDBRetriesExceeded:
        raise webob.exc.HTTPConflict(
            _('Max retries of DB transaction exceeded attempting '
              'to create resource class: %(name)s, please'
              'try again.') %
            {'name': data['name']})

    req.response.location = util.resource_class_url(req.environ, rc)
    req.response.status = 201
    req.response.content_type = None
    return req.response


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.2')
def delete_resource_class(req):
    """DELETE to destroy a single resource class.

    On success return a 204 and an empty body.
    """
    name = util.wsgi_path_item(req.environ, 'name')
    context = req.environ['placement.context']
    context.can(policies.DELETE)
    # The containing application will catch a not found here.
    rc = rp_obj.ResourceClass.get_by_name(context, name)
    try:
        rc.destroy()
    except exception.ResourceClassCannotDeleteStandard as exc:
        raise webob.exc.HTTPBadRequest(
            _('Error in delete resource class: %(error)s') % {'error': exc})
    except exception.ResourceClassInUse as exc:
        raise webob.exc.HTTPConflict(
            _('Error in delete resource class: %(error)s') % {'error': exc})
    req.response.status = 204
    req.response.content_type = None
    return req.response


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.2')
@util.check_accept('application/json')
def get_resource_class(req):
    """Get a single resource class.

    On success return a 200 with an application/json body representing
    the resource class.
    """
    name = util.wsgi_path_item(req.environ, 'name')
    context = req.environ['placement.context']
    context.can(policies.SHOW)
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]
    # The containing application will catch a not found here.
    rc = rp_obj.ResourceClass.get_by_name(context, name)

    req.response.body = encodeutils.to_utf8(jsonutils.dumps(
        _serialize_resource_class(req.environ, rc))
    )
    req.response.content_type = 'application/json'
    if want_version.matches((1, 15)):
        req.response.cache_control = 'no-cache'
        # Non-custom resource classes will return None from pick_last_modified,
        # so the 'or' causes utcnow to be used.
        last_modified = util.pick_last_modified(None, rc) or timeutils.utcnow(
            with_timezone=True)
        req.response.last_modified = last_modified
    return req.response


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.2')
@util.check_accept('application/json')
def list_resource_classes(req):
    """GET a list of resource classes.

    On success return a 200 and an application/json body representing
    a collection of resource classes.
    """
    context = req.environ['placement.context']
    context.can(policies.LIST)
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]
    rcs = rp_obj.ResourceClassList.get_all(context)

    response = req.response
    output, last_modified = _serialize_resource_classes(
        req.environ, rcs, want_version)
    response.body = encodeutils.to_utf8(jsonutils.dumps(output))
    response.content_type = 'application/json'
    if want_version.matches((1, 15)):
        response.last_modified = last_modified
        response.cache_control = 'no-cache'
    return response


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.2', '1.6')
@util.require_content('application/json')
def update_resource_class(req):
    """PUT to update a single resource class.

    On success return a 200 response with a representation of the updated
    resource class.
    """
    name = util.wsgi_path_item(req.environ, 'name')
    context = req.environ['placement.context']
    context.can(policies.UPDATE)

    data = util.extract_json(req.body, schema.PUT_RC_SCHEMA_V1_2)

    # The containing application will catch a not found here.
    rc = rp_obj.ResourceClass.get_by_name(context, name)

    rc.name = data['name']

    try:
        rc.save()
    except exception.ResourceClassExists:
        raise webob.exc.HTTPConflict(
            _('Resource class already exists: %(name)s') %
            {'name': rc.name})
    except exception.ResourceClassCannotUpdateStandard:
        raise webob.exc.HTTPBadRequest(
            _('Cannot update standard resource class %(rp_name)s') %
            {'rp_name': name})

    req.response.body = encodeutils.to_utf8(jsonutils.dumps(
        _serialize_resource_class(req.environ, rc))
    )
    req.response.status = 200
    req.response.content_type = 'application/json'
    return req.response


@wsgi_wrapper.PlacementWsgify  # noqa
@microversion.version_handler('1.7')
def update_resource_class(req):
    """PUT to create or validate the existence of single resource class.

    On a successful create return 201. Return 204 if the class already
    exists. If the resource class is not a custom resource class, return
    a 400. 409 might be a better choice, but 400 aligns with previous code.
    """
    name = util.wsgi_path_item(req.environ, 'name')
    context = req.environ['placement.context']
    context.can(policies.UPDATE)

    # Use JSON validation to validation resource class name.
    util.extract_json('{"name": "%s"}' % name, schema.PUT_RC_SCHEMA_V1_2)

    status = 204
    try:
        rc = rp_obj.ResourceClass.get_by_name(context, name)
    except exception.NotFound:
        try:
            rc = rp_obj.ResourceClass(context, name=name)
            rc.create()
            status = 201
        # We will not see ResourceClassCannotUpdateStandard because
        # that was already caught when validating the {name}.
        except exception.ResourceClassExists:
            # Someone just now created the class, so stick with 204
            pass

    req.response.status = status
    req.response.content_type = None
    req.response.location = util.resource_class_url(req.environ, rc)
    return req.response
