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
"""Aggregate handlers for Placement API."""

from oslo_db import exception as db_exc
from oslo_serialization import jsonutils
from oslo_utils import encodeutils
from oslo_utils import timeutils
import webob

from nova.api.openstack.placement import errors
from nova.api.openstack.placement import exception
from nova.api.openstack.placement import microversion
from nova.api.openstack.placement.objects import resource_provider as rp_obj
from nova.api.openstack.placement.policies import aggregate as policies
from nova.api.openstack.placement.schemas import aggregate as schema
from nova.api.openstack.placement import util
from nova.api.openstack.placement import wsgi_wrapper
from nova.i18n import _


_INCLUDE_GENERATION_VERSION = (1, 19)


def _send_aggregates(req, resource_provider, aggregate_uuids):
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]
    response = req.response
    response.status = 200
    payload = _serialize_aggregates(aggregate_uuids)
    if want_version.matches(min_version=_INCLUDE_GENERATION_VERSION):
        payload['resource_provider_generation'] = resource_provider.generation
    response.body = encodeutils.to_utf8(
        jsonutils.dumps(payload))
    response.content_type = 'application/json'
    if want_version.matches((1, 15)):
        req.response.cache_control = 'no-cache'
        # We never get an aggregate itself, we get the list of aggregates
        # that are associated with a resource provider. We don't record the
        # time when that association was made and the time when an aggregate
        # uuid was created is not relevant, so here we punt and use utcnow.
        req.response.last_modified = timeutils.utcnow(with_timezone=True)
    return response


def _serialize_aggregates(aggregate_uuids):
    return {'aggregates': aggregate_uuids}


def _set_aggregates(resource_provider, aggregate_uuids,
                    increment_generation=False):
    """Set aggregates for the resource provider.

    If increment generation is true, the resource provider generation
    will be incremented if possible. If that fails (because something
    else incremented the generation in another thread), a
    ConcurrentUpdateDetected will be raised.
    """
    # NOTE(cdent): It's not clear what the DBDuplicateEntry handling
    # is doing here, set_aggregates already handles that, but I'm leaving
    # it here because it was already there.
    try:
        resource_provider.set_aggregates(
            aggregate_uuids, increment_generation=increment_generation)
    except exception.ConcurrentUpdateDetected as exc:
        raise webob.exc.HTTPConflict(
            _('Update conflict: %(error)s') % {'error': exc},
            comment=errors.CONCURRENT_UPDATE)
    except db_exc.DBDuplicateEntry as exc:
        raise webob.exc.HTTPConflict(
            _('Update conflict: %(error)s') % {'error': exc})


@wsgi_wrapper.PlacementWsgify
@util.check_accept('application/json')
@microversion.version_handler('1.1')
def get_aggregates(req):
    """GET a list of aggregates associated with a resource provider.

    If the resource provider does not exist return a 404.

    On success return a 200 with an application/json body containing a
    list of aggregate uuids.
    """
    context = req.environ['placement.context']
    context.can(policies.LIST)
    uuid = util.wsgi_path_item(req.environ, 'uuid')
    resource_provider = rp_obj.ResourceProvider.get_by_uuid(
        context, uuid)
    aggregate_uuids = resource_provider.get_aggregates()

    return _send_aggregates(req, resource_provider, aggregate_uuids)


@wsgi_wrapper.PlacementWsgify
@util.require_content('application/json')
@microversion.version_handler('1.1')
def set_aggregates(req):
    context = req.environ['placement.context']
    context.can(policies.UPDATE)
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]
    consider_generation = want_version.matches(
        min_version=_INCLUDE_GENERATION_VERSION)
    put_schema = schema.PUT_AGGREGATES_SCHEMA_V1_1
    if consider_generation:
        put_schema = schema.PUT_AGGREGATES_SCHEMA_V1_19
    uuid = util.wsgi_path_item(req.environ, 'uuid')
    resource_provider = rp_obj.ResourceProvider.get_by_uuid(
        context, uuid)
    data = util.extract_json(req.body, put_schema)
    if consider_generation:
        # Check for generation conflict
        rp_gen = data['resource_provider_generation']
        if resource_provider.generation != rp_gen:
            raise webob.exc.HTTPConflict(
                _("Resource provider's generation already changed. Please "
                  "update the generation and try again."),
                comment=errors.CONCURRENT_UPDATE)
        aggregate_uuids = data['aggregates']
    else:
        aggregate_uuids = data
    _set_aggregates(resource_provider, aggregate_uuids,
                    increment_generation=consider_generation)

    return _send_aggregates(req, resource_provider, aggregate_uuids)
