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

from nova.api.openstack.placement import microversion
from nova.api.openstack.placement import util
from nova.api.openstack.placement import wsgi_wrapper
from nova import objects


PUT_AGGREGATES_SCHEMA = {
    "type": "array",
    "items": {
        "type": "string",
        "format": "uuid"
    },
    "uniqueItems": True
}


def _send_aggregates(response, aggregate_uuids):
    response.status = 200
    response.body = encodeutils.to_utf8(
        jsonutils.dumps(_serialize_aggregates(aggregate_uuids)))
    response.content_type = 'application/json'
    return response


def _serialize_aggregates(aggregate_uuids):
    return {'aggregates': aggregate_uuids}


@wsgi_wrapper.PlacementWsgify
@util.check_accept('application/json')
def get_aggregates(req):
    """GET a list of aggregates associated with a resource provider.

    If the resource provider does not exist return a 404.

    On success return a 200 with an application/json body containing a
    list of aggregate uuids.
    """
    microversion.raise_http_status_code_if_not_version(req, 404, (1, 1))
    context = req.environ['placement.context']
    uuid = util.wsgi_path_item(req.environ, 'uuid')
    resource_provider = objects.ResourceProvider.get_by_uuid(
        context, uuid)
    aggregate_uuids = resource_provider.get_aggregates()

    return _send_aggregates(req.response, aggregate_uuids)


@wsgi_wrapper.PlacementWsgify
@util.require_content('application/json')
def set_aggregates(req):
    microversion.raise_http_status_code_if_not_version(req, 404, (1, 1))
    context = req.environ['placement.context']
    uuid = util.wsgi_path_item(req.environ, 'uuid')
    resource_provider = objects.ResourceProvider.get_by_uuid(
        context, uuid)
    aggregate_uuids = util.extract_json(req.body, PUT_AGGREGATES_SCHEMA)
    resource_provider.set_aggregates(aggregate_uuids)

    return _send_aggregates(req.response, aggregate_uuids)
