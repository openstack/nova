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
import functools

import six
from webob import exc

from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.compute import api as compute_api
from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova import utils

ALIAS = "os-aggregates"
LOG = logging.getLogger(__name__)
authorize = extensions.extension_authorizer('compute', "v3:" + ALIAS)


def _get_context(req):
    return req.environ['nova.context']


def get_host_from_body(fn):
    """Makes sure that the host exists."""
    @functools.wraps(fn)
    def wrapped(self, req, id, body, *args, **kwargs):
        if not self.is_valid_body(body, fn.wsgi_action):
            raise exc.HTTPBadRequest(explanation=_("Invalid request body"))
        host = body[fn.wsgi_action].get('host')
        if host is None:
            raise exc.HTTPBadRequest(
                explanation=_("Could not find host to be set in "
                              "request body"))
        if not isinstance(host, six.string_types):
            raise exc.HTTPBadRequest(
                explanation=_("The value of host must be a string"))
        return fn(self, req, id, host, *args, **kwargs)
    return wrapped


class AggregateController(wsgi.Controller):
    """The Host Aggregates API controller for the OpenStack API."""
    def __init__(self):
        self.api = compute_api.AggregateAPI()

    @extensions.expected_errors(())
    def index(self, req):
        """Returns a list a host aggregate's id, name, availability_zone."""
        context = _get_context(req)
        authorize(context, action='index')
        aggregates = self.api.get_aggregate_list(context)
        return {'aggregates': [self._marshall_aggregate(a)['aggregate']
                               for a in aggregates]}

    @extensions.expected_errors((400, 409))
    @wsgi.response(201)
    def create(self, req, body):
        """Creates an aggregate, given its name and
        optional availability zone.
        """
        context = _get_context(req)
        authorize(context, action='create')
        if not self.is_valid_body(body, 'aggregate'):
            raise exc.HTTPBadRequest(explanation=_("Invalid request body"))
        try:
            host_aggregate = body["aggregate"]
            name = host_aggregate["name"]
        except KeyError as e:
            msg = _("Could not find %s parameter in the request") % e.args[0]
            raise exc.HTTPBadRequest(explanation=msg)
        avail_zone = host_aggregate.get("availability_zone")
        try:
            utils.check_string_length(name, "Aggregate name", 1, 255)
        except exception.InvalidInput as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        try:
            aggregate = self.api.create_aggregate(context, name, avail_zone)
        except exception.AggregateNameExists as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        except exception.InvalidAggregateAction as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())
        return self._marshall_aggregate(aggregate)

    @extensions.expected_errors(404)
    def show(self, req, id):
        """Shows the details of an aggregate, hosts and metadata included."""
        context = _get_context(req)
        authorize(context, action='show')
        try:
            aggregate = self.api.get_aggregate(context, id)
        except exception.AggregateNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        return self._marshall_aggregate(aggregate)

    @extensions.expected_errors((400, 404, 409))
    def update(self, req, id, body):
        """Updates the name and/or availability_zone of given aggregate."""
        context = _get_context(req)
        authorize(context, action='update')
        if not self.is_valid_body(body, 'aggregate'):
            raise exc.HTTPBadRequest(explanation=_("Invalid request body"))
        updates = body["aggregate"]
        if len(updates) < 1:
            raise exc.HTTPBadRequest(
                explanation=_("Request body is empty"))
        for key in updates.keys():
            if key not in ["name", "availability_zone"]:
                msg = _("Invalid key %s in request body.") % key
                raise exc.HTTPBadRequest(explanation=msg)

        if 'name' in updates:
            try:
                utils.check_string_length(updates['name'], "Aggregate name", 1,
                                          255)
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

        return self._marshall_aggregate(aggregate)

    @extensions.expected_errors(404)
    @wsgi.response(204)
    def delete(self, req, id):
        """Removes an aggregate by id."""
        context = _get_context(req)
        authorize(context, action='delete')
        try:
            self.api.delete_aggregate(context, id)
        except exception.AggregateNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())

    @extensions.expected_errors((400, 404, 409))
    @get_host_from_body
    @wsgi.action('add_host')
    @wsgi.response(202)
    def _add_host(self, req, id, host):
        """Adds a host to the specified aggregate."""
        context = _get_context(req)
        authorize(context, action='add_host')
        try:
            aggregate = self.api.add_host_to_aggregate(context, id, host)
        except (exception.AggregateNotFound,
                exception.ComputeHostNotFound) as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except (exception.AggregateHostExists,
                exception.InvalidAggregateAction) as e:
            raise exc.HTTPConflict(explanation=e.format_message())
        return self._marshall_aggregate(aggregate)

    @extensions.expected_errors((400, 404, 409))
    @get_host_from_body
    @wsgi.action('remove_host')
    @wsgi.response(202)
    def _remove_host(self, req, id, host):
        """Removes a host from the specified aggregate."""
        context = _get_context(req)
        authorize(context, action='remove_host')
        try:
            aggregate = self.api.remove_host_from_aggregate(context, id, host)
        except (exception.AggregateNotFound, exception.AggregateHostNotFound,
                exception.ComputeHostNotFound):
            msg = _('Cannot remove host %(host)s in aggregate %(id)s') % {
                        'host': host, 'id': id}
            raise exc.HTTPNotFound(explanation=msg)
        except exception.InvalidAggregateAction:
            msg = _('Cannot remove host %(host)s in aggregate %(id)s') % {
                        'host': host, 'id': id}
            raise exc.HTTPConflict(explanation=msg)
        return self._marshall_aggregate(aggregate)

    @extensions.expected_errors((400, 404))
    @wsgi.action('set_metadata')
    def _set_metadata(self, req, id, body):
        """Replaces the aggregate's existing metadata with new metadata."""
        context = _get_context(req)
        authorize(context, action='set_metadata')
        if not self.is_valid_body(body, 'set_metadata'):
            raise exc.HTTPBadRequest(explanation=_("Invalid request body"))
        if not self.is_valid_body(body["set_metadata"], "metadata"):
            raise exc.HTTPBadRequest(
                explanation=_("Invalid request format for metadata"))
        metadata = body["set_metadata"]["metadata"]
        try:
            aggregate = self.api.update_aggregate_metadata(context,
                                                           id, metadata)
        except exception.AggregateNotFound as e:
            raise exc.HTTPNotFound(explanation=e.format_message())
        except exception.InvalidAggregateAction as e:
            raise exc.HTTPBadRequest(explanation=e.format_message())

        return self._marshall_aggregate(aggregate)

    def _marshall_aggregate(self, aggregate):
        _aggregate = {}
        for key, value in aggregate.items():
            # NOTE(danms): The original API specified non-TZ-aware timestamps
            if isinstance(value, datetime.datetime):
                value = value.replace(tzinfo=None)
            _aggregate[key] = value
        return {"aggregate": _aggregate}


class Aggregates(extensions.V3APIExtensionBase):
    """Admin-only aggregate administration."""

    name = "Aggregates"
    alias = ALIAS
    version = 1

    def get_resources(self):
        resources = [extensions.ResourceExtension(
                                            self.alias,
                                            AggregateController(),
                                            member_actions={'action': 'POST'})]
        return resources

    def get_controller_extensions(self):
        return []
