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
"""Placement API handlers for setting and deleting allocations."""

import collections
import copy

from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import encodeutils
import webob

from nova.api.openstack.placement import microversion
from nova.api.openstack.placement import util
from nova.api.openstack.placement import wsgi_wrapper
from nova import exception
from nova.i18n import _
from nova import objects


LOG = logging.getLogger(__name__)

ALLOCATION_SCHEMA = {
    "type": "object",
    "properties": {
        "allocations": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "resource_provider": {
                        "type": "object",
                        "properties": {
                            "uuid": {
                                "type": "string",
                                "format": "uuid"
                            }
                        },
                        "additionalProperties": False,
                        "required": ["uuid"]
                    },
                    "resources": {
                        "type": "object",
                        "minProperties": 1,
                        "patternProperties": {
                            "^[0-9A-Z_]+$": {
                                "type": "integer",
                                "minimum": 1,
                            }
                        },
                        "additionalProperties": False
                    }
                },
                "required": [
                    "resource_provider",
                    "resources"
                ],
                "additionalProperties": False
            }
        }
    },
    "required": ["allocations"],
    "additionalProperties": False
}

ALLOCATION_SCHEMA_V1_8 = copy.deepcopy(ALLOCATION_SCHEMA)
ALLOCATION_SCHEMA_V1_8['properties']['project_id'] = {'type': 'string',
                                                      'minLength': 1,
                                                      'maxLength': 255}
ALLOCATION_SCHEMA_V1_8['properties']['user_id'] = {'type': 'string',
                                                   'minLength': 1,
                                                   'maxLength': 255}
ALLOCATION_SCHEMA_V1_8['required'].extend(['project_id', 'user_id'])


def _allocations_dict(allocations, key_fetcher, resource_provider=None):
    """Turn allocations into a dict of resources keyed by key_fetcher."""
    allocation_data = collections.defaultdict(dict)

    for allocation in allocations:
        key = key_fetcher(allocation)
        if 'resources' not in allocation_data[key]:
            allocation_data[key]['resources'] = {}

        resource_class = allocation.resource_class
        allocation_data[key]['resources'][resource_class] = allocation.used

        if not resource_provider:
            generation = allocation.resource_provider.generation
            allocation_data[key]['generation'] = generation

    result = {'allocations': allocation_data}
    if resource_provider:
        result['resource_provider_generation'] = resource_provider.generation
    return result


def _serialize_allocations_for_consumer(allocations):
    """Turn a list of allocations into a dict by resource provider uuid.

    {
        'allocations': {
            RP_UUID_1: {
                'generation': GENERATION,
                'resources': {
                    'DISK_GB': 4,
                    'VCPU': 2
                }
            },
            RP_UUID_2: {
                'generation': GENERATION,
                'resources': {
                    'DISK_GB': 6,
                    'VCPU': 3
                }
            }
        }
    }
    """
    return _allocations_dict(allocations,
                             lambda x: x.resource_provider.uuid)


def _serialize_allocations_for_resource_provider(allocations,
                                                 resource_provider):
    """Turn a list of allocations into a dict by consumer id.

    {'resource_provider_generation': GENERATION,
     'allocations':
       CONSUMER_ID_1: {
           'resources': {
              'DISK_GB': 4,
              'VCPU': 2
           }
       },
       CONSUMER_ID_2: {
           'resources': {
              'DISK_GB': 6,
              'VCPU': 3
           }
       }
    }
    """
    return _allocations_dict(allocations, lambda x: x.consumer_id,
                             resource_provider=resource_provider)


@wsgi_wrapper.PlacementWsgify
@util.check_accept('application/json')
def list_for_consumer(req):
    """List allocations associated with a consumer."""
    context = req.environ['placement.context']
    consumer_id = util.wsgi_path_item(req.environ, 'consumer_uuid')

    # NOTE(cdent): There is no way for a 404 to be returned here,
    # only an empty result. We do not have a way to validate a
    # consumer id.
    allocations = objects.AllocationList.get_all_by_consumer_id(
        context, consumer_id)

    allocations_json = jsonutils.dumps(
        _serialize_allocations_for_consumer(allocations))

    req.response.status = 200
    req.response.body = encodeutils.to_utf8(allocations_json)
    req.response.content_type = 'application/json'
    return req.response


@wsgi_wrapper.PlacementWsgify
@util.check_accept('application/json')
def list_for_resource_provider(req):
    """List allocations associated with a resource provider."""
    # TODO(cdent): On a shared resource provider (for example a
    # giant disk farm) this list could get very long. At the moment
    # we have no facility for limiting the output. Given that we are
    # using a dict of dicts for the output we are potentially limiting
    # ourselves in terms of sorting and filtering.
    context = req.environ['placement.context']
    uuid = util.wsgi_path_item(req.environ, 'uuid')

    # confirm existence of resource provider so we get a reasonable
    # 404 instead of empty list
    try:
        resource_provider = objects.ResourceProvider.get_by_uuid(
            context, uuid)
    except exception.NotFound as exc:
        raise webob.exc.HTTPNotFound(
            _("Resource provider '%(rp_uuid)s' not found: %(error)s") %
            {'rp_uuid': uuid, 'error': exc})

    allocations = objects.AllocationList.get_all_by_resource_provider_uuid(
        context, uuid)

    allocations_json = jsonutils.dumps(
        _serialize_allocations_for_resource_provider(
            allocations, resource_provider))

    req.response.status = 200
    req.response.body = encodeutils.to_utf8(allocations_json)
    req.response.content_type = 'application/json'
    return req.response


def _set_allocations(req, schema):
    context = req.environ['placement.context']
    consumer_uuid = util.wsgi_path_item(req.environ, 'consumer_uuid')
    data = util.extract_json(req.body, schema)
    allocation_data = data['allocations']

    # If the body includes an allocation for a resource provider
    # that does not exist, raise a 400.
    allocation_objects = []
    for allocation in allocation_data:
        resource_provider_uuid = allocation['resource_provider']['uuid']

        try:
            resource_provider = objects.ResourceProvider.get_by_uuid(
                context, resource_provider_uuid)
        except exception.NotFound:
            raise webob.exc.HTTPBadRequest(
                _("Allocation for resource provider '%(rp_uuid)s' "
                  "that does not exist.") %
                {'rp_uuid': resource_provider_uuid})

        resources = allocation['resources']
        for resource_class in resources:
            allocation = objects.Allocation(
                resource_provider=resource_provider,
                consumer_id=consumer_uuid,
                resource_class=resource_class,
                used=resources[resource_class])
            allocation_objects.append(allocation)

    allocations = objects.AllocationList(
        context,
        objects=allocation_objects,
        project_id=data.get('project_id'),
        user_id=data.get('user_id'),
    )

    try:
        allocations.create_all()
        LOG.debug("Successfully wrote allocations %s", allocations)
    # InvalidInventory is a parent for several exceptions that
    # indicate either that Inventory is not present, or that
    # capacity limits have been exceeded.
    except exception.NotFound as exc:
        raise webob.exc.HTTPBadRequest(
                _("Unable to allocate inventory for resource provider "
                  "%(rp_uuid)s: %(error)s") %
            {'rp_uuid': resource_provider_uuid, 'error': exc})
    except exception.InvalidInventory as exc:
        raise webob.exc.HTTPConflict(
            _('Unable to allocate inventory: %(error)s') % {'error': exc})
    except exception.ConcurrentUpdateDetected as exc:
        raise webob.exc.HTTPConflict(
            _('Inventory changed while attempting to allocate: %(error)s') %
            {'error': exc})

    req.response.status = 204
    req.response.content_type = None
    return req.response


@wsgi_wrapper.PlacementWsgify
@microversion.version_handler('1.0', '1.7')
@util.require_content('application/json')
def set_allocations(req):
    return _set_allocations(req, ALLOCATION_SCHEMA)


@wsgi_wrapper.PlacementWsgify  # noqa
@microversion.version_handler('1.8')
@util.require_content('application/json')
def set_allocations(req):
    return _set_allocations(req, ALLOCATION_SCHEMA_V1_8)


@wsgi_wrapper.PlacementWsgify
def delete_allocations(req):
    context = req.environ['placement.context']
    consumer_uuid = util.wsgi_path_item(req.environ, 'consumer_uuid')

    allocations = objects.AllocationList.get_all_by_consumer_id(
        context, consumer_uuid)
    if allocations:
        try:
            allocations.delete_all()
        # NOTE(pumaranikar): Following NotFound exception added in the case
        # when allocation is deleted from allocations list by some other
        # activity. In that case, delete_all() will throw a NotFound exception.
        except exception.NotFound as exc:
            raise webob.exc.HTPPNotFound(
                  _("Allocation for consumer with id %(id)s not found."
                    "error: %(error)s") %
                  {'id': consumer_uuid, 'error': exc})
    else:
        raise webob.exc.HTTPNotFound(
            _("No allocations for consumer '%(consumer_uuid)s'") %
            {'consumer_uuid': consumer_uuid})
    LOG.debug("Successfully deleted allocations %s", allocations)

    req.response.status = 204
    req.response.content_type = None
    return req.response
