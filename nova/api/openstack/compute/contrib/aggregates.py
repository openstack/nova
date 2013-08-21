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

from webob import exc

from nova.api.openstack import extensions
from nova.compute import api as compute_api
from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova import utils

LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('compute', 'aggregates')


def _get_context(req):
    return req.environ['nova.context']


def get_host_from_body(fn):
    """Makes sure that the host exists."""
    def wrapped(self, req, id, body, *args, **kwargs):
        if len(body) == 1 and "host" in body:
            host = body['host']
        else:
            raise exc.HTTPBadRequest()
        return fn(self, req, id, host, *args, **kwargs)
    return wrapped


class AggregateController(object):
    """The Host Aggregates API controller for the OpenStack API."""
    def __init__(self):
        self.api = compute_api.AggregateAPI()

    def index(self, req):
        """Returns a list a host aggregate's id, name, availability_zone."""
        context = _get_context(req)
        authorize(context)
        aggregates = self.api.get_aggregate_list(context)
        return {'aggregates': [self._marshall_aggregate(a)['aggregate']
                               for a in aggregates]}

    def create(self, req, body):
        """Creates an aggregate, given its name and availability_zone."""
        context = _get_context(req)
        authorize(context)

        if len(body) != 1:
            raise exc.HTTPBadRequest()
        try:
            host_aggregate = body["aggregate"]
            name = host_aggregate["name"]
            avail_zone = host_aggregate["availability_zone"]
        except KeyError:
            raise exc.HTTPBadRequest()

        try:
            utils.check_string_length(name, "Aggregate name", 1, 255)
        except exception.InvalidInput as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        if len(host_aggregate) != 2:
            raise exc.HTTPBadRequest()

        try:
            aggregate = self.api.create_aggregate(context, name, avail_zone)
        except exception.AggregateNameExists as e:
            LOG.info(e)
            raise exc.HTTPConflict()
        except exception.InvalidAggregateAction as e:
            LOG.info(e)
            raise
        return self._marshall_aggregate(aggregate)

    def show(self, req, id):
        """Shows the details of an aggregate, hosts and metadata included."""
        context = _get_context(req)
        authorize(context)
        try:
            aggregate = self.api.get_aggregate(context, id)
        except exception.AggregateNotFound:
            LOG.info(_("Cannot show aggregate: %s"), id)
            raise exc.HTTPNotFound()
        return self._marshall_aggregate(aggregate)

    def update(self, req, id, body):
        """Updates the name and/or availability_zone of given aggregate."""
        context = _get_context(req)
        authorize(context)

        if len(body) != 1:
            raise exc.HTTPBadRequest()
        try:
            updates = body["aggregate"]
        except KeyError:
            raise exc.HTTPBadRequest()

        if len(updates) < 1:
            raise exc.HTTPBadRequest()

        for key in updates.keys():
            if key not in ["name", "availability_zone"]:
                raise exc.HTTPBadRequest()

        if 'name' in updates:
            try:
                utils.check_string_length(updates['name'], "Aggregate name", 1,
                                          255)
            except exception.InvalidInput as e:
                raise exc.HTTPBadRequest(explanation=e.format_message())

        try:
            aggregate = self.api.update_aggregate(context, id, updates)
        except exception.AggregateNotFound:
            LOG.info(_('Cannot update aggregate: %s'), id)
            raise exc.HTTPNotFound()

        return self._marshall_aggregate(aggregate)

    def delete(self, req, id):
        """Removes an aggregate by id."""
        context = _get_context(req)
        authorize(context)
        try:
            self.api.delete_aggregate(context, id)
        except exception.AggregateNotFound:
            LOG.info(_('Cannot delete aggregate: %s'), id)
            raise exc.HTTPNotFound()

    def action(self, req, id, body):
        _actions = {
            'add_host': self._add_host,
            'remove_host': self._remove_host,
            'set_metadata': self._set_metadata,
        }
        for action, data in body.iteritems():
            if action not in _actions.keys():
                msg = _('Aggregates does not have %s action') % action
                raise exc.HTTPBadRequest(explanation=msg)
            return _actions[action](req, id, data)

        raise exc.HTTPBadRequest(explanation=_("Invalid request body"))

    @get_host_from_body
    def _add_host(self, req, id, host):
        """Adds a host to the specified aggregate."""
        context = _get_context(req)
        authorize(context)
        try:
            aggregate = self.api.add_host_to_aggregate(context, id, host)
        except (exception.AggregateNotFound, exception.ComputeHostNotFound):
            LOG.info(_('Cannot add host %(host)s in aggregate %(id)s'),
                     {'host': host, 'id': id})
            raise exc.HTTPNotFound()
        except (exception.AggregateHostExists,
                exception.InvalidAggregateAction) as e:
            LOG.info(_('Cannot add host %(host)s in aggregate %(id)s'),
                     {'host': host, 'id': id})
            raise exc.HTTPConflict(explanation=e.format_message())
        return self._marshall_aggregate(aggregate)

    @get_host_from_body
    def _remove_host(self, req, id, host):
        """Removes a host from the specified aggregate."""
        context = _get_context(req)
        authorize(context)
        try:
            aggregate = self.api.remove_host_from_aggregate(context, id, host)
        except (exception.AggregateNotFound, exception.AggregateHostNotFound,
                exception.ComputeHostNotFound):
            LOG.info(_('Cannot remove host %(host)s in aggregate %(id)s'),
                     {'host': host, 'id': id})
            raise exc.HTTPNotFound()
        except exception.InvalidAggregateAction:
            LOG.info(_('Cannot remove host %(host)s in aggregate %(id)s'),
                     {'host': host, 'id': id})
            raise exc.HTTPConflict()
        return self._marshall_aggregate(aggregate)

    def _set_metadata(self, req, id, body):
        """Replaces the aggregate's existing metadata with new metadata."""
        context = _get_context(req)
        authorize(context)

        if len(body) != 1:
            raise exc.HTTPBadRequest()
        try:
            metadata = body["metadata"]
        except KeyError:
            raise exc.HTTPBadRequest()
        try:
            aggregate = self.api.update_aggregate_metadata(context,
                                                           id, metadata)
        except exception.AggregateNotFound:
            LOG.info(_('Cannot set metadata %(metadata)s in aggregate %(id)s'),
                     {'metadata': metadata, 'id': id})
            raise exc.HTTPNotFound()

        return self._marshall_aggregate(aggregate)

    def _marshall_aggregate(self, aggregate):
        _aggregate = {}
        for key, value in aggregate.items():
            # NOTE(danms): The original API specified non-TZ-aware timestamps
            if isinstance(value, datetime.datetime):
                value = value.replace(tzinfo=None)
            _aggregate[key] = value
        return {"aggregate": _aggregate}


class Aggregates(extensions.ExtensionDescriptor):
    """Admin-only aggregate administration."""

    name = "Aggregates"
    alias = "os-aggregates"
    namespace = "http://docs.openstack.org/compute/ext/aggregates/api/v1.1"
    updated = "2012-01-12T00:00:00+00:00"

    def __init__(self, ext_mgr):
        ext_mgr.register(self)

    def get_resources(self):
        resources = []
        res = extensions.ResourceExtension('os-aggregates',
                AggregateController(),
                member_actions={"action": "POST", })
        resources.append(res)
        return resources
