# Copyright (c) 2012 Citrix Systems, Inc.
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

"""The Aggregate admin API extension."""

import datetime

from oslo_log import log as logging
import six
from webob import exc

from nova.api.openstack import api_version_request
from nova.api.openstack import common
from nova.api.openstack.compute.schemas import aggregate_images
from nova.api.openstack.compute.schemas import aggregates
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import api as compute
from nova.conductor import api as conductor
from nova import exception
from nova.i18n import _
from nova.policies import aggregates as aggr_policies
from nova import utils

LOG = logging.getLogger(__name__)


def _get_context(req):
    return req.environ['nova.context']


class AggregateController(wsgi.Controller):
    """The Host Aggregates API controller for the OpenStack API."""
    def __init__(self):
        super(AggregateController, self).__init__()
        self.api = compute.AggregateAPI()
        self.conductor_tasks = conductor.ComputeTaskAPI()

    @wsgi.expected_errors(())
    def index(self, req):
        """Returns a list a host aggregate's id, name, availability_zone."""
        context = _get_context(req)
        context.can(aggr_policies.POLICY_ROOT % 'index', target={})
        aggregates = self.api.get_aggregate_list(context)
        return {'aggregates': [self._marshall_aggregate(req, a)['aggregate']
                               for a in aggregates]}

    # NOTE(gmann): Returns 200 for backwards compatibility but should be 201
    # as this operation complete the creation of aggregates resource.
    @wsgi.expected_errors((400, 409))
    @validation.schema(aggregates.create_v20, '2.0', '2.0')
    @validation.schema(aggregates.create, '2.1')
    def create(self, req, body):
        """Creates an aggregate, given its name and
        optional availability zone.
        """
        context = _get_context(req)
        context.can(aggr_policies.POLICY_ROOT % 'create', target={})
        host_aggregate = body["aggregate"]
        name = common.normalize_name(host_aggregate["name"])
        avail_zone = host_aggregate.get("availability_zone")
        if avail_zone:
            avail_zone = common.normalize_name(avail_zone)

        try:
            aggregate = self.api.create_aggregate(context, name, avail_zone)
        except exception.AggregateNameExists as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.ObjectActionError:
            raise exc.HTTPConflict(explanation=_(
                'Not all aggregates have been migrated to the API database'))
        except exception.InvalidAggregateAction as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        agg = self._marshall_aggregate(req, aggregate)

        # To maintain the same API result as before the changes for returning
        # nova objects were made.
        del agg['aggregate']['hosts']
        del agg['aggregate']['metadata']

        return agg

    @wsgi.expected_errors((400, 404))
    def show(self, req, id):
        """Shows the details of an aggregate, hosts and metadata included."""
        context = _get_context(req)
        context.can(aggr_policies.POLICY_ROOT % 'show', target={})

        try:
            utils.validate_integer(id, 'id')
        except exception.InvalidInput as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        try:
            aggregate = self.api.get_aggregate(context, id)
        except exception.AggregateNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        return self._marshall_aggregate(req, aggregate)

    @wsgi.expected_errors((400, 404, 409))
    @validation.schema(aggregates.update_v20, '2.0', '2.0')
    @validation.schema(aggregates.update, '2.1')
    def update(self, req, id, body):
        """Updates the name and/or availability_zone of given aggregate."""
        context = _get_context(req)
        context.can(aggr_policies.POLICY_ROOT % 'update', target={})
        updates = body["aggregate"]
        if 'name' in updates:
            updates['name'] = common.normalize_name(updates['name'])

        try:
            utils.validate_integer(id, 'id')
        except exception.InvalidInput as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        try:
            aggregate = self.api.update_aggregate(context, id, updates)
        except exception.AggregateNameExists as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.AggregateNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.InvalidAggregateAction as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        return self._marshall_aggregate(req, aggregate)

    # NOTE(gmann): Returns 200 for backwards compatibility but should be 204
    # as this operation complete the deletion of aggregate resource and return
    # no response body.
    @wsgi.expected_errors((400, 404))
    def delete(self, req, id):
        """Removes an aggregate by id."""
        context = _get_context(req)
        context.can(aggr_policies.POLICY_ROOT % 'delete', target={})

        try:
            utils.validate_integer(id, 'id')
        except exception.InvalidInput as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        try:
            self.api.delete_aggregate(context, id)
        except exception.AggregateNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.InvalidAggregateAction as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

    # NOTE(gmann): Returns 200 for backwards compatibility but should be 202
    # for representing async API as this API just accepts the request and
    # request hypervisor driver to complete the same in async mode.
    @wsgi.expected_errors((400, 404, 409))
    @wsgi.action('add_host')
    @validation.schema(aggregates.add_host)
    def _add_host(self, req, id, body):
        """Adds a host to the specified aggregate."""
        host = body['add_host']['host']

        context = _get_context(req)
        context.can(aggr_policies.POLICY_ROOT % 'add_host', target={})

        try:
            utils.validate_integer(id, 'id')
        except exception.InvalidInput as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        try:
            aggregate = self.api.add_host_to_aggregate(context, id, host)
        except (exception.AggregateNotFound,
                exception.HostMappingNotFound,
                exception.ComputeHostNotFound) as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except (exception.AggregateHostExists,
                exception.InvalidAggregateAction) as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        return self._marshall_aggregate(req, aggregate)

    # NOTE(gmann): Returns 200 for backwards compatibility but should be 202
    # for representing async API as this API just accepts the request and
    # request hypervisor driver to complete the same in async mode.
    @wsgi.expected_errors((400, 404, 409))
    @wsgi.action('remove_host')
    @validation.schema(aggregates.remove_host)
    def _remove_host(self, req, id, body):
        """Removes a host from the specified aggregate."""
        host = body['remove_host']['host']

        context = _get_context(req)
        context.can(aggr_policies.POLICY_ROOT % 'remove_host', target={})

        try:
            utils.validate_integer(id, 'id')
        except exception.InvalidInput as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        try:
            aggregate = self.api.remove_host_from_aggregate(context, id, host)
        except (exception.AggregateNotFound,
                exception.AggregateHostNotFound,
                exception.ComputeHostNotFound) as e:
            LOG.error('Failed to remove host %s from aggregate %s. Error: %s',
                      host, id, six.text_type(e))
            msg = _('Cannot remove host %(host)s in aggregate %(id)s') % {
                        'host': host, 'id': id}
            raise exc.HTTPNotFound(explanation=msg)
        except (exception.InvalidAggregateAction,
                exception.ResourceProviderUpdateConflict) as e:
            LOG.error('Failed to remove host %s from aggregate %s. Error: %s',
                      host, id, six.text_type(e))
            msg = _('Cannot remove host %(host)s in aggregate %(id)s') % {
                        'host': host, 'id': id}
            raise exc.HTTPConflict(explanation=msg)
        return self._marshall_aggregate(req, aggregate)

    @wsgi.expected_errors((400, 404))
    @wsgi.action('set_metadata')
    @validation.schema(aggregates.set_metadata)
    def _set_metadata(self, req, id, body):
        """Replaces the aggregate's existing metadata with new metadata."""
        context = _get_context(req)
        context.can(aggr_policies.POLICY_ROOT % 'set_metadata', target={})

        try:
            utils.validate_integer(id, 'id')
        except exception.InvalidInput as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        metadata = body["set_metadata"]["metadata"]
        try:
            aggregate = self.api.update_aggregate_metadata(context,
                                                           id, metadata)
        except exception.AggregateNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.InvalidAggregateAction as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        return self._marshall_aggregate(req, aggregate)

    def _marshall_aggregate(self, req, aggregate):
        _aggregate = {}
        for key, value in self._build_aggregate_items(req, aggregate):
            # NOTE(danms): The original API specified non-TZ-aware timestamps
            if isinstance(value, datetime.datetime):
                value = value.replace(tzinfo=None)
            _aggregate[key] = value
        return {"aggregate": _aggregate}

    def _build_aggregate_items(self, req, aggregate):
        show_uuid = api_version_request.is_supported(req, min_version="2.41")
        keys = aggregate.obj_fields
        # NOTE(rlrossit): Within the compute API, metadata will always be
        # set on the aggregate object (at a minimum to {}). Because of this,
        # we can freely use getattr() on keys in obj_extra_fields (in this
        # case it is only ['availability_zone']) without worrying about
        # lazy-loading an unset variable
        for key in keys:
            if ((aggregate.obj_attr_is_set(key) or
                    key in aggregate.obj_extra_fields) and
                    (show_uuid or key != 'uuid')):
                yield key, getattr(aggregate, key)

    @wsgi.Controller.api_version('2.81')
    @wsgi.response(202)
    @wsgi.expected_errors((400, 404))
    @validation.schema(aggregate_images.aggregate_images_v2_81)
    def images(self, req, id, body):
        """Allows image cache management requests."""
        context = _get_context(req)
        context.can(aggr_policies.NEW_POLICY_ROOT % 'images', target={})

        try:
            utils.validate_integer(id, 'id')
        except exception.InvalidInput as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        image_ids = []
        for image_req in body.get('cache'):
            image_ids.append(image_req['id'])

        if image_ids != list(set(image_ids)):
            raise exc.HTTPBadRequest(
                explanation=_('Duplicate images in request'))

        try:
            aggregate = self.api.get_aggregate(context, id)
        except exception.AggregateNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

        try:
            self.conductor_tasks.cache_images(context, aggregate, image_ids)
        except exception.NovaException as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
