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

from oslo_serialization import jsonutils
from oslo_utils import encodeutils
from oslo_utils import timeutils

from nova.api.openstack.placement import microversion
from nova.api.openstack.placement.schemas import aggregate as schema
from nova.api.openstack.placement import util
from nova.api.openstack.placement import wsgi_wrapper
from nova.objects import resource_provider as rp_obj


def _send_aggregates(req, aggregate_uuids):
    want_version = req.environ[microversion.MICROVERSION_ENVIRON]
    response = req.response
    response.status = 200
    response.body = encodeutils.to_utf8(
        jsonutils.dumps(_serialize_aggregates(aggregate_uuids)))
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
    uuid = util.wsgi_path_item(req.environ, 'uuid')
    resource_provider = rp_obj.ResourceProvider.get_by_uuid(
        context, uuid)
    aggregate_uuids = resource_provider.get_aggregates()

    return _send_aggregates(req, aggregate_uuids)


@wsgi_wrapper.PlacementWsgify
@util.require_content('application/json')
@microversion.version_handler('1.1')
def set_aggregates(req):
    context = req.environ['placement.context']
    uuid = util.wsgi_path_item(req.environ, 'uuid')
    resource_provider = rp_obj.ResourceProvider.get_by_uuid(
        context, uuid)
    aggregate_uuids = util.extract_json(req.body, schema.PUT_AGGREGATES_SCHEMA)
    resource_provider.set_aggregates(aggregate_uuids)

    return _send_aggregates(req, aggregate_uuids)
