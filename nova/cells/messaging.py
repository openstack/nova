# Copyright (c) 2012 Rackspace Hosting
# All Rights Reserved.
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright 2013 Red Hat, Inc.
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

"""
Cell messaging module.

This module defines the different message types that are passed between
cells and the methods that they can call when the target cell has been
reached.

The interface into this module is the MessageRunner class.
"""

import sys
import traceback

from eventlet import queue
from oslo_log import log as logging
import oslo_messaging as messaging
from oslo_serialization import jsonutils
from oslo_utils import excutils
from oslo_utils import importutils
from oslo_utils import timeutils
from oslo_utils import uuidutils
import six
from six.moves import range

from nova.cells import state as cells_state
from nova.cells import utils as cells_utils
from nova import compute
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import task_states
from nova.compute import vm_states
import nova.conf
from nova.consoleauth import rpcapi as consoleauth_rpcapi
from nova import context
from nova.db import base
from nova import exception
from nova.i18n import _
from nova import objects
from nova.objects import base as objects_base
from nova import rpc
from nova import utils

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)

# Separator used between cell names for the 'full cell name' and routing
# path.
_PATH_CELL_SEP = cells_utils.PATH_CELL_SEP


def _reverse_path(path):
    """Reverse a path.  Used for sending responses upstream."""
    path_parts = path.split(_PATH_CELL_SEP)
    path_parts.reverse()
    return _PATH_CELL_SEP.join(path_parts)


def _response_cell_name_from_path(routing_path, neighbor_only=False):
    """Reverse the routing_path.  If we only want to send to our parent,
    set neighbor_only to True.
    """
    path = _reverse_path(routing_path)
    if not neighbor_only or len(path) == 1:
        return path
    return _PATH_CELL_SEP.join(path.split(_PATH_CELL_SEP)[:2])


#
# Message classes.
#


class _BaseMessage(object):
    """Base message class.  It defines data that is passed with every
    single message through every cell.

    Messages are JSON-ified before sending and turned back into a
    class instance when being received.

    Every message has a unique ID.  This is used to route responses
    back to callers.  In the future, this might be used to detect
    receiving the same message more than once.

    routing_path is updated on every hop through a cell.  The current
    cell name is appended to it (cells are separated by
    _PATH_CELL_SEP ('!')).  This is used to tell if we've reached the
    target cell and also to determine the source of a message for
    responses by reversing it.

    hop_count is incremented and compared against max_hop_count.  The
    only current usefulness of this is to break out of a routing loop
    if someone has a broken config.

    fanout means to send to all nova-cells services running in a cell.
    This is useful for capacity and capability broadcasting as well
    as making sure responses get back to the nova-cells service that
    is waiting.
    """

    # Override message_type in a subclass
    message_type = None

    base_attrs_to_json = ['message_type',
                          'ctxt',
                          'method_name',
                          'method_kwargs',
                          'direction',
                          'need_response',
                          'fanout',
                          'uuid',
                          'routing_path',
                          'hop_count',
                          'max_hop_count']

    def __init__(self, msg_runner, ctxt, method_name, method_kwargs,
            direction, need_response=False, fanout=False, uuid=None,
            routing_path=None, hop_count=0, max_hop_count=None,
            **kwargs):
        self.ctxt = ctxt
        self.resp_queue = None
        self.msg_runner = msg_runner
        self.state_manager = msg_runner.state_manager
        # Copy these.
        self.base_attrs_to_json = self.base_attrs_to_json[:]
        # Normally this would just be CONF.cells.name, but going through
        # the msg_runner allows us to stub it more easily.
        self.our_path_part = self.msg_runner.our_name
        self.uuid = uuid
        if self.uuid is None:
            self.uuid = uuidutils.generate_uuid()
        self.method_name = method_name
        self.method_kwargs = method_kwargs
        self.direction = direction
        self.need_response = need_response
        self.fanout = fanout
        self.routing_path = routing_path
        self.hop_count = hop_count
        if max_hop_count is None:
            max_hop_count = CONF.cells.max_hop_count
        self.max_hop_count = max_hop_count
        self.is_broadcast = False
        self._append_hop()
        # Each sub-class should set this when the message is initialized
        self.next_hops = []
        self.resp_queue = None
        self.serializer = objects_base.NovaObjectSerializer()

    def __repr__(self):
        _dict = self._to_dict()
        _dict.pop('method_kwargs')
        return "<%s: %s>" % (self.__class__.__name__, _dict)

    def _append_hop(self):
        """Add our hop to the routing_path."""
        routing_path = (self.routing_path and
                self.routing_path + _PATH_CELL_SEP or '')
        self.routing_path = routing_path + self.our_path_part
        self.hop_count += 1

    def _process_locally(self):
        """Its been determined that we should process this message in this
        cell.  Go through the MessageRunner to call the appropriate
        method for this message.  Catch the response and/or exception and
        encode it within a Response instance.  Return it so the caller
        can potentially return it to another cell... or return it to
        a caller waiting in this cell.
        """
        try:
            resp_value = self.msg_runner._process_message_locally(self)
            failure = False
        except Exception:
            resp_value = sys.exc_info()
            failure = True
            LOG.exception("Error processing message locally")
        return Response(self.ctxt, self.routing_path, resp_value, failure)

    def _setup_response_queue(self):
        """Shortcut to creating a response queue in the MessageRunner."""
        self.resp_queue = self.msg_runner._setup_response_queue(self)

    def _cleanup_response_queue(self):
        """Shortcut to deleting a response queue in the MessageRunner."""
        if self.resp_queue:
            self.msg_runner._cleanup_response_queue(self)
            self.resp_queue = None

    def _wait_for_json_responses(self, num_responses=1):
        """Wait for response(s) to be put into the eventlet queue.  Since
        each queue entry actually contains a list of JSON-ified responses,
        combine them all into a single list to return.

        Destroy the eventlet queue when done.
        """
        if not self.resp_queue:
            # Source is not actually expecting a response
            return
        responses = []
        wait_time = CONF.cells.call_timeout
        try:
            for x in range(num_responses):
                json_responses = self.resp_queue.get(timeout=wait_time)
                responses.extend(json_responses)
        except queue.Empty:
            raise exception.CellTimeout()
        finally:
            self._cleanup_response_queue()
        return responses

    def _send_json_responses(self, json_responses, neighbor_only=False,
            fanout=False):
        """Send list of responses to this message.  Responses passed here
        are JSON-ified.  Targeted messages have a single response while
        Broadcast messages may have multiple responses.

        If this cell was the source of the message, these responses will
        be returned from self.process().

        Otherwise, we will route the response to the source of the
        request.  If 'neighbor_only' is True, the response will be sent
        to the neighbor cell, not the original requester.  Broadcast
        messages get aggregated at each hop, so neighbor_only will be
        True for those messages.
        """
        if not self.need_response:
            return
        if self.source_is_us():
            responses = []
            for json_response in json_responses:
                responses.append(Response.from_json(self.ctxt, json_response))
            return responses
        direction = self.direction == 'up' and 'down' or 'up'
        response_kwargs = {'orig_message': self.to_json(),
                           'responses': json_responses}
        target_cell = _response_cell_name_from_path(self.routing_path,
                neighbor_only=neighbor_only)
        response = self.msg_runner._create_response_message(self.ctxt,
                direction, target_cell, self.uuid, response_kwargs,
                fanout=fanout)
        response.process()

    def _send_response(self, response, neighbor_only=False):
        """Send a response to this message.  If the source of the
        request was ourselves, just return the response.  It'll be
        passed back to the caller of self.process().  See DocString for
        _send_json_responses() as it handles most of the real work for
        this method.

        'response' is an instance of Response class.
        """
        if not self.need_response:
            return
        if self.source_is_us():
            return response
        self._send_json_responses([response.to_json()],
                                  neighbor_only=neighbor_only)

    def _send_response_from_exception(self, exc_info):
        """Take an exception as returned from sys.exc_info(), encode
        it in a Response, and send it.
        """
        response = Response(self.ctxt, self.routing_path, exc_info, True)
        return self._send_response(response)

    def _to_dict(self):
        """Convert a message to a dictionary.  Only used internally."""
        _dict = {}
        for key in self.base_attrs_to_json:
            _dict[key] = getattr(self, key)
        return _dict

    def to_json(self):
        """Convert a message into JSON for sending to a sibling cell."""
        _dict = self._to_dict()
        # Convert context to dict.
        _dict['ctxt'] = _dict['ctxt'].to_dict()
        # NOTE(comstud): 'method_kwargs' needs special serialization
        # because it may contain objects.
        method_kwargs = _dict['method_kwargs']
        for k, v in method_kwargs.items():
            method_kwargs[k] = self.serializer.serialize_entity(self.ctxt, v)
        return jsonutils.dumps(_dict)

    def source_is_us(self):
        """Did this cell create this message?"""
        return self.routing_path == self.our_path_part

    def process(self):
        """Process a message.  Deal with it locally and/or forward it to a
        sibling cell.

        Override in a subclass.
        """
        raise NotImplementedError()


class _TargetedMessage(_BaseMessage):
    """A targeted message is a message that is destined for a specific
    single cell.

    'target_cell' can be a full cell name like 'api!child-cell' or it can
    be an instance of the CellState class if the target is a neighbor cell.
    """
    message_type = 'targeted'

    def __init__(self, msg_runner, ctxt, method_name, method_kwargs,
            direction, target_cell, **kwargs):
        super(_TargetedMessage, self).__init__(msg_runner, ctxt,
                method_name, method_kwargs, direction, **kwargs)
        if isinstance(target_cell, cells_state.CellState):
            # Neighbor cell or ourselves.  Convert it to a 'full path'.
            if target_cell.is_me:
                target_cell = self.our_path_part
            else:
                target_cell = '%s%s%s' % (self.our_path_part,
                                          _PATH_CELL_SEP,
                                          target_cell.name)
        # NOTE(alaski): This occurs when hosts are specified with no cells
        # routing information.
        if target_cell is None:
            reason = _('No cell given in routing path.')
            raise exception.CellRoutingInconsistency(reason=reason)
        self.target_cell = target_cell
        self.base_attrs_to_json.append('target_cell')

    def _get_next_hop(self):
        """Return the cell name for the next hop.  If the next hop is
        the current cell, return None.
        """
        if self.target_cell == self.routing_path:
            return self.state_manager.my_cell_state
        target_cell = self.target_cell
        routing_path = self.routing_path
        current_hops = routing_path.count(_PATH_CELL_SEP)
        next_hop_num = current_hops + 1
        dest_hops = target_cell.count(_PATH_CELL_SEP)
        if dest_hops < current_hops:
            reason_args = {'target_cell': target_cell,
                           'routing_path': routing_path}
            reason = _("destination is %(target_cell)s but routing_path "
                       "is %(routing_path)s") % reason_args
            raise exception.CellRoutingInconsistency(reason=reason)
        dest_name_parts = target_cell.split(_PATH_CELL_SEP)
        if (_PATH_CELL_SEP.join(dest_name_parts[:next_hop_num]) !=
                routing_path):
            reason_args = {'target_cell': target_cell,
                           'routing_path': routing_path}
            reason = _("destination is %(target_cell)s but routing_path "
                       "is %(routing_path)s") % reason_args
            raise exception.CellRoutingInconsistency(reason=reason)
        next_hop_name = dest_name_parts[next_hop_num]
        if self.direction == 'up':
            next_hop = self.state_manager.get_parent_cell(next_hop_name)
        else:
            next_hop = self.state_manager.get_child_cell(next_hop_name)
        if not next_hop:
            cell_type = 'parent' if self.direction == 'up' else 'child'
            reason_args = {'cell_type': cell_type,
                           'target_cell': target_cell}
            reason = _("Unknown %(cell_type)s when routing to "
                       "%(target_cell)s") % reason_args
            raise exception.CellRoutingInconsistency(reason=reason)
        return next_hop

    def process(self):
        """Process a targeted message.  This is called for all cells
        that touch this message.  If the local cell is the one that
        created this message, we reply directly with a Response instance.
        If the local cell is not the target, an eventlet queue is created
        and we wait for the response to show up via another thread
        receiving the Response back.

        Responses to targeted messages are routed directly back to the
        source.  No eventlet queues are created in intermediate hops.

        All exceptions for processing the message across the whole
        routing path are caught and encoded within the Response and
        returned to the caller.
        """
        try:
            next_hop = self._get_next_hop()
        except Exception:
            exc_info = sys.exc_info()
            LOG.exception("Error locating next hop for message")
            return self._send_response_from_exception(exc_info)

        if next_hop.is_me:
            # Final destination.
            response = self._process_locally()
            return self._send_response(response)

        # Need to forward via neighbor cell.
        if self.need_response and self.source_is_us():
            # A response is needed and the source of the message is
            # this cell.  Create the eventlet queue.
            self._setup_response_queue()
            wait_for_response = True
        else:
            wait_for_response = False

        try:
            # This is inside the try block, so we can encode the
            # exception and return it to the caller.
            if self.hop_count >= self.max_hop_count:
                raise exception.CellMaxHopCountReached(
                        hop_count=self.hop_count)
            next_hop.send_message(self)
        except Exception:
            exc_info = sys.exc_info()
            err_str = "Failed to send message to cell: %(next_hop)s"
            LOG.exception(err_str, {'next_hop': next_hop})
            self._cleanup_response_queue()
            return self._send_response_from_exception(exc_info)

        if wait_for_response:
            # Targeted messages only have 1 response.
            remote_response = self._wait_for_json_responses()[0]
            return Response.from_json(self.ctxt, remote_response)


class _BroadcastMessage(_BaseMessage):
    """A broadcast message.  This means to call a method in every single
    cell going in a certain direction.
    """
    message_type = 'broadcast'

    def __init__(self, msg_runner, ctxt, method_name, method_kwargs,
            direction, run_locally=True, **kwargs):
        super(_BroadcastMessage, self).__init__(msg_runner, ctxt,
                method_name, method_kwargs, direction, **kwargs)
        # The local cell creating this message has the option
        # to be able to process the message locally or not.
        self.run_locally = run_locally
        self.is_broadcast = True

    def _get_next_hops(self):
        """Set the next hops and return the number of hops.  The next
        hops may include ourself.
        """
        if self.hop_count >= self.max_hop_count:
            return []
        if self.direction == 'down':
            return self.state_manager.get_child_cells()
        else:
            return self.state_manager.get_parent_cells()

    def _send_to_cells(self, target_cells):
        """Send a message to multiple cells."""
        for cell in target_cells:
            cell.send_message(self)

    def _send_json_responses(self, json_responses):
        """Responses to broadcast messages always need to go to the
        neighbor cell from which we received this message.  That
        cell aggregates the responses and makes sure to forward them
        to the correct source.
        """
        return super(_BroadcastMessage, self)._send_json_responses(
                json_responses, neighbor_only=True, fanout=True)

    def process(self):
        """Process a broadcast message.  This is called for all cells
        that touch this message.

        The message is sent to all cells in the certain direction and
        the creator of this message has the option of whether or not
        to process it locally as well.

        If responses from all cells are required, each hop creates an
        eventlet queue and waits for responses from its immediate
        neighbor cells.  All responses are then aggregated into a
        single list and are returned to the neighbor cell until the
        source is reached.

        When the source is reached, a list of Response instances are
        returned to the caller.

        All exceptions for processing the message across the whole
        routing path are caught and encoded within the Response and
        returned to the caller.  It is possible to get a mix of
        successful responses and failure responses.  The caller is
        responsible for dealing with this.
        """
        try:
            next_hops = self._get_next_hops()
        except Exception:
            exc_info = sys.exc_info()
            LOG.exception("Error locating next hops for message")
            return self._send_response_from_exception(exc_info)

        # Short circuit if we don't need to respond
        if not self.need_response:
            if self.run_locally:
                self._process_locally()
            self._send_to_cells(next_hops)
            return

        # We'll need to aggregate all of the responses (from ourself
        # and our sibling cells) into 1 response
        try:
            self._setup_response_queue()
            self._send_to_cells(next_hops)
        except Exception:
            # Error just trying to send to cells.  Send a single response
            # with the failure.
            exc_info = sys.exc_info()
            LOG.exception("Error sending message to next hops.")
            self._cleanup_response_queue()
            return self._send_response_from_exception(exc_info)

        if self.run_locally:
            # Run locally and store the Response.
            local_response = self._process_locally()
        else:
            local_response = None

        try:
            remote_responses = self._wait_for_json_responses(
                    num_responses=len(next_hops))
        except Exception:
            # Error waiting for responses, most likely a timeout.
            # Send a single response back with the failure.
            exc_info = sys.exc_info()
            LOG.exception("Error waiting for responses from neighbor cells")
            return self._send_response_from_exception(exc_info)

        if local_response:
            remote_responses.append(local_response.to_json())
        return self._send_json_responses(remote_responses)


class _ResponseMessage(_TargetedMessage):
    """A response message is really just a special targeted message,
    saying to call 'parse_responses' when we reach the source of a 'call'.

    The 'fanout' attribute on this message may be true if we're responding
    to a broadcast or if we're about to respond to the source of an
    original target message.  Because multiple nova-cells services may
    be running within a cell, we need to make sure the response gets
    back to the correct one, so we have to fanout.
    """
    message_type = 'response'

    def __init__(self, msg_runner, ctxt, method_name, method_kwargs,
            direction, target_cell, response_uuid, **kwargs):
        super(_ResponseMessage, self).__init__(msg_runner, ctxt,
                method_name, method_kwargs, direction, target_cell, **kwargs)
        self.response_uuid = response_uuid
        self.base_attrs_to_json.append('response_uuid')

    def process(self):
        """Process a response.  If the target is the local cell, process
        the response here.  Otherwise, forward it to where it needs to
        go.
        """
        next_hop = self._get_next_hop()
        if next_hop.is_me:
            self._process_locally()
            return
        if self.fanout is False:
            # Really there's 1 more hop on each of these below, but
            # it doesn't matter for this logic.
            target_hops = self.target_cell.count(_PATH_CELL_SEP)
            current_hops = self.routing_path.count(_PATH_CELL_SEP)
            if current_hops + 1 == target_hops:
                # Next hop is the target.. so we must fanout.  See
                # DocString above.
                self.fanout = True
        next_hop.send_message(self)


#
# Methods that may be called when processing messages after reaching
# a target cell.
#


class _BaseMessageMethods(base.Base):
    """Base class for defining methods by message types."""
    def __init__(self, msg_runner):
        super(_BaseMessageMethods, self).__init__()
        self.msg_runner = msg_runner
        self.state_manager = msg_runner.state_manager
        self.compute_api = compute.API()
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()
        self.consoleauth_rpcapi = consoleauth_rpcapi.ConsoleAuthAPI()
        self.host_api = compute.HostAPI()

    def task_log_get_all(self, message, task_name, period_beginning,
                         period_ending, host, state):
        """Get task logs from the DB.  The message could have
        directly targeted this cell, or it could have been a broadcast
        message.

        If 'host' is not None, filter by host.
        If 'state' is not None, filter by state.
        """
        task_logs = self.db.task_log_get_all(message.ctxt, task_name,
                                             period_beginning,
                                             period_ending,
                                             host=host,
                                             state=state)
        return jsonutils.to_primitive(task_logs)


class _ResponseMessageMethods(_BaseMessageMethods):
    """Methods that are called from a ResponseMessage.  There's only
    1 method (parse_responses) and it is called when the message reaches
    the source of a 'call'.  All we do is stuff the response into the
    eventlet queue to signal the caller that's waiting.
    """
    def parse_responses(self, message, orig_message, responses):
        self.msg_runner._put_response(message.response_uuid,
                responses)


class _TargetedMessageMethods(_BaseMessageMethods):
    """These are the methods that can be called when routing a message
    to a specific cell.
    """
    def __init__(self, *args, **kwargs):
        super(_TargetedMessageMethods, self).__init__(*args, **kwargs)

    def build_instances(self, message, build_inst_kwargs):
        """Parent cell told us to schedule new instance creation."""
        self.msg_runner.scheduler.build_instances(message, build_inst_kwargs)

    def run_compute_api_method(self, message, method_info):
        """Run a method in the compute api class."""
        method = method_info['method']
        fn = getattr(self.compute_api, method, None)
        if not fn:
            detail = _("Unknown method '%(method)s' in compute API")
            raise exception.CellServiceAPIMethodNotFound(
                    detail=detail % {'method': method})
        args = list(method_info['method_args'])
        # 1st arg is instance_uuid that we need to turn into the
        # instance object.
        instance_uuid = args[0]
        # NOTE: compute/api.py loads these when retrieving an instance for an
        # API request, so there's a good chance that this is what was loaded.
        expected_attrs = ['metadata', 'system_metadata', 'security_groups',
                          'info_cache']

        try:
            instance = objects.Instance.get_by_uuid(message.ctxt,
                    instance_uuid, expected_attrs=expected_attrs)
            args[0] = instance
        except exception.InstanceNotFound:
            with excutils.save_and_reraise_exception():
                # Must be a race condition.  Let's try to resolve it by
                # telling the top level cells that this instance doesn't
                # exist.
                instance = objects.Instance(context=message.ctxt,
                                            uuid=instance_uuid)
                self.msg_runner.instance_destroy_at_top(message.ctxt,
                                                        instance)
        return fn(message.ctxt, *args, **method_info['method_kwargs'])

    def update_capabilities(self, message, cell_name, capabilities):
        """A child cell told us about their capabilities."""
        LOG.debug("Received capabilities from child cell "
                  "%(cell_name)s: %(capabilities)s",
                  {'cell_name': cell_name, 'capabilities': capabilities})
        self.state_manager.update_cell_capabilities(cell_name,
                capabilities)
        # Go ahead and update our parents now that a child updated us
        self.msg_runner.tell_parents_our_capabilities(message.ctxt)

    def update_capacities(self, message, cell_name, capacities):
        """A child cell told us about their capacity."""
        LOG.debug("Received capacities from child cell "
                  "%(cell_name)s: %(capacities)s",
                  {'cell_name': cell_name, 'capacities': capacities})
        self.state_manager.update_cell_capacities(cell_name,
                capacities)
        # Go ahead and update our parents now that a child updated us
        self.msg_runner.tell_parents_our_capacities(message.ctxt)

    def announce_capabilities(self, message):
        """A parent cell has told us to send our capabilities, so let's
        do so.
        """
        self.msg_runner.tell_parents_our_capabilities(message.ctxt)

    def announce_capacities(self, message):
        """A parent cell has told us to send our capacity, so let's
        do so.
        """
        self.msg_runner.tell_parents_our_capacities(message.ctxt)

    def service_get_by_compute_host(self, message, host_name):
        """Return the service entry for a compute host."""
        return objects.Service.get_by_compute_host(message.ctxt, host_name)

    def service_update(self, message, host_name, binary, params_to_update):
        """Used to enable/disable a service. For compute services, setting to
        disabled stops new builds arriving on that host.

        :param host_name: the name of the host machine that the service is
                          running
        :param binary: The name of the executable that the service runs as
        :param params_to_update: eg. {'disabled': True}
        """
        return self.host_api._service_update(message.ctxt, host_name, binary,
                                             params_to_update)

    def service_delete(self, message, service_id):
        """Deletes the specified service."""
        self.host_api._service_delete(message.ctxt, service_id)

    def proxy_rpc_to_manager(self, message, host_name, rpc_message,
                             topic, timeout):
        """Proxy RPC to the given compute topic."""
        # Check that the host exists.
        objects.Service.get_by_compute_host(message.ctxt, host_name)

        topic, _sep, server = topic.partition('.')

        cctxt = rpc.get_client(messaging.Target(topic=topic,
                                                server=server or None))
        method = rpc_message['method']
        kwargs = rpc_message['args']

        if message.need_response:
            cctxt = cctxt.prepare(timeout=timeout)
            return cctxt.call(message.ctxt, method, **kwargs)
        else:
            cctxt.cast(message.ctxt, method, **kwargs)

    def compute_node_get(self, message, compute_id):
        """Get compute node by ID or UUID."""
        if uuidutils.is_uuid_like(compute_id):
            return objects.ComputeNode.get_by_uuid(message.ctxt, compute_id)
        return objects.ComputeNode.get_by_id(message.ctxt, compute_id)

    def actions_get(self, message, instance_uuid):
        actions = self.db.actions_get(message.ctxt, instance_uuid)
        return jsonutils.to_primitive(actions)

    def action_get_by_request_id(self, message, instance_uuid, request_id):
        action = self.db.action_get_by_request_id(message.ctxt, instance_uuid,
                                                  request_id)
        return jsonutils.to_primitive(action)

    def action_events_get(self, message, action_id):
        action_events = self.db.action_events_get(message.ctxt, action_id)
        return jsonutils.to_primitive(action_events)

    def validate_console_port(self, message, instance_uuid, console_port,
                              console_type):
        """Validate console port with child cell compute node."""
        # 1st arg is instance_uuid that we need to turn into the
        # instance object.
        try:
            instance = objects.Instance.get_by_uuid(message.ctxt,
                                                    instance_uuid)
        except exception.InstanceNotFound:
            with excutils.save_and_reraise_exception():
                # Must be a race condition.  Let's try to resolve it by
                # telling the top level cells that this instance doesn't
                # exist.
                instance = objects.Instance(context=message.ctxt,
                                            uuid=instance_uuid)
                self.msg_runner.instance_destroy_at_top(message.ctxt,
                                                        instance)
        return self.compute_rpcapi.validate_console_port(message.ctxt,
                instance, console_port, console_type)

    def get_migrations(self, message, filters):
        return self.compute_api.get_migrations(message.ctxt, filters)

    def instance_update_from_api(self, message, instance,
                                 expected_vm_state,
                                 expected_task_state,
                                 admin_state_reset):
        """Update an instance in this cell."""
        if not admin_state_reset:
            # NOTE(comstud): We don't want to nuke this cell's view
            # of vm_state and task_state unless it's a forced reset
            # via admin API.
            instance.obj_reset_changes(['vm_state', 'task_state'])
        # NOTE(alaski): A cell should be authoritative for its system_metadata
        # and metadata so we don't want to sync it down from the api.
        instance.obj_reset_changes(['metadata', 'system_metadata'])
        with instance.skip_cells_sync():
            instance.save(expected_vm_state=expected_vm_state,
                          expected_task_state=expected_task_state)

    def _call_compute_api_with_obj(self, ctxt, instance, method, *args,
                                   **kwargs):
        try:
            # NOTE(comstud): We need to refresh the instance from this
            # cell's view in the DB.
            instance.refresh()
        except exception.InstanceNotFound:
            with excutils.save_and_reraise_exception():
                # Must be a race condition.  Let's try to resolve it by
                # telling the top level cells that this instance doesn't
                # exist.
                instance = objects.Instance(context=ctxt,
                                            uuid=instance.uuid)
                self.msg_runner.instance_destroy_at_top(ctxt,
                                                        instance)
        except exception.InstanceInfoCacheNotFound:
            if method not in ('delete', 'force_delete'):
                raise

        fn = getattr(self.compute_api, method, None)
        return fn(ctxt, instance, *args, **kwargs)

    def start_instance(self, message, instance):
        """Start an instance via compute_api.start()."""
        self._call_compute_api_with_obj(message.ctxt, instance, 'start')

    def stop_instance(self, message, instance, clean_shutdown=True):
        """Stop an instance via compute_api.stop()."""
        do_cast = not message.need_response
        return self._call_compute_api_with_obj(message.ctxt, instance,
                                               'stop', do_cast=do_cast,
                                               clean_shutdown=clean_shutdown)

    def reboot_instance(self, message, instance, reboot_type):
        """Reboot an instance via compute_api.reboot()."""
        self._call_compute_api_with_obj(message.ctxt, instance, 'reboot',
                                        reboot_type=reboot_type)

    def suspend_instance(self, message, instance):
        """Suspend an instance via compute_api.suspend()."""
        self._call_compute_api_with_obj(message.ctxt, instance, 'suspend')

    def resume_instance(self, message, instance):
        """Resume an instance via compute_api.suspend()."""
        self._call_compute_api_with_obj(message.ctxt, instance, 'resume')

    def get_host_uptime(self, message, host_name):
        return self.host_api.get_host_uptime(message.ctxt, host_name)

    def terminate_instance(self, message, instance, delete_type='delete'):
        self._call_compute_api_with_obj(message.ctxt, instance, delete_type)

    def soft_delete_instance(self, message, instance):
        self._call_compute_api_with_obj(message.ctxt, instance, 'soft_delete')

    def pause_instance(self, message, instance):
        """Pause an instance via compute_api.pause()."""
        self._call_compute_api_with_obj(message.ctxt, instance, 'pause')

    def unpause_instance(self, message, instance):
        """Unpause an instance via compute_api.pause()."""
        self._call_compute_api_with_obj(message.ctxt, instance, 'unpause')

    def resize_instance(self, message, instance, flavor,
                        extra_instance_updates, clean_shutdown=True):
        """Resize an instance via compute_api.resize()."""
        self._call_compute_api_with_obj(message.ctxt, instance, 'resize',
                                        flavor_id=flavor['flavorid'],
                                        clean_shutdown=clean_shutdown,
                                        **extra_instance_updates)

    def live_migrate_instance(self, message, instance, block_migration,
                              disk_over_commit, host_name):
        """Live migrate an instance via compute_api.live_migrate()."""
        self._call_compute_api_with_obj(message.ctxt, instance,
                                        'live_migrate', block_migration,
                                        disk_over_commit, host_name)

    def revert_resize(self, message, instance):
        """Revert a resize for an instance in its cell."""
        self._call_compute_api_with_obj(message.ctxt, instance,
                                        'revert_resize')

    def confirm_resize(self, message, instance):
        """Confirm a resize for an instance in its cell."""
        self._call_compute_api_with_obj(message.ctxt, instance,
                                        'confirm_resize')

    def reset_network(self, message, instance):
        """Reset networking for an instance in its cell."""
        self._call_compute_api_with_obj(message.ctxt, instance,
                                        'reset_network')

    def inject_network_info(self, message, instance):
        """Inject networking for an instance in its cell."""
        self._call_compute_api_with_obj(message.ctxt, instance,
                                        'inject_network_info')

    def snapshot_instance(self, message, instance, image_id):
        """Snapshot an instance in its cell."""
        instance.refresh()
        instance.task_state = task_states.IMAGE_SNAPSHOT_PENDING
        instance.save(expected_task_state=[None])
        self.compute_rpcapi.snapshot_instance(message.ctxt,
                                              instance,
                                              image_id)

    def backup_instance(self, message, instance, image_id,
                        backup_type, rotation):
        """Backup an instance in its cell."""
        instance.refresh()
        instance.task_state = task_states.IMAGE_BACKUP
        instance.save(expected_task_state=[None])
        self.compute_rpcapi.backup_instance(message.ctxt,
                                            instance,
                                            image_id,
                                            backup_type,
                                            rotation)

    def rebuild_instance(self, message, instance, image_href, admin_password,
                         files_to_inject, preserve_ephemeral, kwargs):
        kwargs['preserve_ephemeral'] = preserve_ephemeral
        self._call_compute_api_with_obj(message.ctxt, instance, 'rebuild',
                                        image_href, admin_password,
                                        files_to_inject, **kwargs)

    def set_admin_password(self, message, instance, new_pass):
        self._call_compute_api_with_obj(message.ctxt, instance,
                'set_admin_password', new_pass)


class _BroadcastMessageMethods(_BaseMessageMethods):
    """These are the methods that can be called as a part of a broadcast
    message.
    """
    def _at_the_top(self):
        """Are we the API level?"""
        return not self.state_manager.get_parent_cells()

    def _get_expected_vm_state(self, instance):
        """To attempt to address out-of-order messages, do some sanity
        checking on the VM states.  Add some requirements for
        vm_state to the instance.save() call if necessary.
        """
        expected_vm_state_map = {
                # For updates containing 'vm_state' of 'building',
                # only allow them to occur if the DB already says
                # 'building' or if the vm_state is None.  None
                # really shouldn't be possible as instances always
                # start out in 'building' anyway.. but just in case.
                vm_states.BUILDING: [vm_states.BUILDING, None]}

        if instance.obj_attr_is_set('vm_state'):
            return expected_vm_state_map.get(instance.vm_state)

    def _get_expected_task_state(self, instance):
        """To attempt to address out-of-order messages, do some sanity
        checking on the task states.  Add some requirements for
        task_state to the instance.save() call if necessary.
        """
        expected_task_state_map = {
                # Always allow updates when task_state doesn't change,
                # but also make sure we don't set resize/rebuild task
                # states for old messages when we've potentially already
                # processed the ACTIVE/None messages.  Ie, these checks
                # will prevent stomping on any ACTIVE/None messages
                # we already processed.
                task_states.REBUILD_BLOCK_DEVICE_MAPPING:
                        [task_states.REBUILD_BLOCK_DEVICE_MAPPING,
                         task_states.REBUILDING],
                task_states.REBUILD_SPAWNING:
                        [task_states.REBUILD_SPAWNING,
                         task_states.REBUILD_BLOCK_DEVICE_MAPPING,
                         task_states.REBUILDING],
                task_states.RESIZE_MIGRATING:
                        [task_states.RESIZE_MIGRATING,
                         task_states.RESIZE_PREP],
                task_states.RESIZE_MIGRATED:
                        [task_states.RESIZE_MIGRATED,
                         task_states.RESIZE_MIGRATING,
                         task_states.RESIZE_PREP],
                task_states.RESIZE_FINISH:
                        [task_states.RESIZE_FINISH,
                         task_states.RESIZE_MIGRATED,
                         task_states.RESIZE_MIGRATING,
                         task_states.RESIZE_PREP]}

        if instance.obj_attr_is_set('task_state'):
            return expected_task_state_map.get(instance.task_state)

    def instance_update_at_top(self, message, instance, **kwargs):
        """Update an instance in the DB if we're a top level cell."""
        if not self._at_the_top():
            return

        # Remove things that we can't update in the top level cells.
        # 'metadata' is only updated in the API cell, so don't overwrite
        # it based on what child cells say.  Make sure to update
        # 'cell_name' based on the routing path.
        items_to_remove = ['id', 'security_groups', 'volumes', 'cell_name',
                           'name', 'metadata']
        instance.obj_reset_changes(items_to_remove)
        instance.cell_name = _reverse_path(message.routing_path)

        # instance.display_name could be unicode
        instance_repr = utils.get_obj_repr_unicode(instance)
        LOG.debug("Got update for instance: %(instance)s",
                  {'instance': instance_repr}, instance_uuid=instance.uuid)

        expected_vm_state = self._get_expected_vm_state(instance)
        expected_task_state = self._get_expected_task_state(instance)

        # It's possible due to some weird condition that the instance
        # was already set as deleted... so we'll attempt to update
        # it with permissions that allows us to read deleted.
        with utils.temporary_mutation(message.ctxt, read_deleted="yes"):
            try:
                with instance.skip_cells_sync():
                    instance.save(expected_vm_state=expected_vm_state,
                                  expected_task_state=expected_task_state)
            except exception.InstanceNotFound:
                # FIXME(comstud): Strange.  Need to handle quotas here,
                # if we actually want this code to remain..
                instance.create()
            except exception.NotFound:
                # Can happen if we try to update a deleted instance's
                # network information, for example.
                pass

    def instance_destroy_at_top(self, message, instance, **kwargs):
        """Destroy an instance from the DB if we're a top level cell."""
        if not self._at_the_top():
            return
        LOG.debug("Got update to delete instance",
                  instance_uuid=instance.uuid)
        try:
            instance.destroy()
        except exception.InstanceNotFound:
            pass
        except exception.ObjectActionError:
            # NOTE(alaski): instance_destroy_at_top will sometimes be called
            # when an instance does not exist in a cell but does in the parent.
            # In that case instance.id is not set which causes instance.destroy
            # to fail thinking that the object has already been destroyed.
            # That's the right assumption for it to make because without cells
            # that would be true.  But for cells we'll try to pull the actual
            # instance and try to delete it again.
            try:
                instance = objects.Instance.get_by_uuid(message.ctxt,
                        instance.uuid)
                instance.destroy()
            except exception.InstanceNotFound:
                pass

    def instance_delete_everywhere(self, message, instance, delete_type,
                                   **kwargs):
        """Call compute API delete() or soft_delete() in every cell.
        This is used when the API cell doesn't know what cell an instance
        belongs to but the instance was requested to be deleted or
        soft-deleted.  So, we'll run it everywhere.
        """
        LOG.debug("Got broadcast to %(delete_type)s delete instance",
                  {'delete_type': delete_type}, instance=instance)
        if delete_type == 'soft':
            self.compute_api.soft_delete(message.ctxt, instance)
        else:
            self.compute_api.delete(message.ctxt, instance)

    def instance_fault_create_at_top(self, message, instance_fault, **kwargs):
        """Destroy an instance from the DB if we're a top level cell."""
        if not self._at_the_top():
            return
        items_to_remove = ['id']
        for key in items_to_remove:
            instance_fault.pop(key, None)
        LOG.debug("Got message to create instance fault: %s", instance_fault)
        fault = objects.InstanceFault(context=message.ctxt)
        fault.update(instance_fault)
        fault.create()

    def bw_usage_update_at_top(self, message, bw_update_info, **kwargs):
        """Update Bandwidth usage in the DB if we're a top level cell."""
        if not self._at_the_top():
            return
        self.db.bw_usage_update(message.ctxt, **bw_update_info)

    def _sync_instance(self, ctxt, instance):
        if instance.deleted:
            self.msg_runner.instance_destroy_at_top(ctxt, instance)
        else:
            self.msg_runner.instance_update_at_top(ctxt, instance)

    def sync_instances(self, message, project_id, updated_since, deleted,
                       **kwargs):
        projid_str = project_id is None and "<all>" or project_id
        since_str = updated_since is None and "<all>" or updated_since
        LOG.info("Forcing a sync of instances, project_id="
                 "%(projid_str)s, updated_since=%(since_str)s",
                 {'projid_str': projid_str, 'since_str': since_str})
        if updated_since is not None:
            updated_since = timeutils.parse_isotime(updated_since)
        instances = cells_utils.get_instances_to_sync(message.ctxt,
                updated_since=updated_since, project_id=project_id,
                deleted=deleted)
        for instance in instances:
            self._sync_instance(message.ctxt, instance)

    def service_get_all(self, message, filters):
        if filters is None:
            filters = {}
        disabled = filters.pop('disabled', None)
        services = objects.ServiceList.get_all(message.ctxt, disabled=disabled)
        ret_services = []
        for service in services:
            for key, val in filters.items():
                if getattr(service, key) != val:
                    break
            else:
                ret_services.append(service)
        return ret_services

    def compute_node_get_all(self, message, hypervisor_match):
        """Return compute nodes in this cell."""
        if hypervisor_match is not None:
            return objects.ComputeNodeList.get_by_hypervisor(message.ctxt,
                                                             hypervisor_match)
        return objects.ComputeNodeList.get_all(message.ctxt)

    def compute_node_stats(self, message):
        """Return compute node stats from this cell."""
        return self.db.compute_node_statistics(message.ctxt)

    def consoleauth_delete_tokens(self, message, instance_uuid):
        """Delete consoleauth tokens for an instance in API cells."""
        if not self._at_the_top():
            return
        self.consoleauth_rpcapi.delete_tokens_for_instance(message.ctxt,
                                                           instance_uuid)

    def bdm_update_or_create_at_top(self, message, bdm, create):
        """Create or update a block device mapping in API cells.  If
        create is True, only try to create.  If create is None, try to
        update but fall back to create.  If create is False, only attempt
        to update.  This maps to nova-conductor's behavior.
        """
        if not self._at_the_top():
            return
        items_to_remove = ['id']
        for key in items_to_remove:
            bdm.pop(key, None)
        if create is None:
            LOG.debug('Calling db.block_device_mapping_update_or_create from '
                      'API cell with values: %s', bdm)
            self.db.block_device_mapping_update_or_create(message.ctxt,
                                                          bdm,
                                                          legacy=False)
            return
        elif create is True:
            LOG.debug('Calling db.block_device_mapping_create from API '
                      'cell with values: %s', bdm)
            self.db.block_device_mapping_create(message.ctxt, bdm,
                                                legacy=False)
            return
        # Unfortunately this update call wants BDM ID... but we don't know
        # what it is in this cell.  Search for it.. try matching either
        # device_name or volume_id.
        dev_name = bdm['device_name']
        vol_id = bdm['volume_id']
        instance_bdms = self.db.block_device_mapping_get_all_by_instance(
                message.ctxt, bdm['instance_uuid'])
        for instance_bdm in instance_bdms:
            if dev_name and instance_bdm['device_name'] == dev_name:
                break
            if vol_id and instance_bdm['volume_id'] == vol_id:
                break
        else:
            LOG.warning("No match when trying to update BDM: %(bdm)s",
                        dict(bdm=bdm))
            return
        LOG.debug('Calling db.block_device_mapping_update from API cell with '
                  'bdm id %s and values: %s', instance_bdm['id'], bdm)
        self.db.block_device_mapping_update(message.ctxt,
                                            instance_bdm['id'], bdm,
                                            legacy=False)

    def bdm_destroy_at_top(self, message, instance_uuid, device_name,
                           volume_id):
        """Destroy a block device mapping in API cells by device name
        or volume_id.  device_name or volume_id can be None, but not both.
        """
        if not self._at_the_top():
            return
        if device_name:
            self.db.block_device_mapping_destroy_by_instance_and_device(
                    message.ctxt, instance_uuid, device_name)
        elif volume_id:
            self.db.block_device_mapping_destroy_by_instance_and_volume(
                    message.ctxt, instance_uuid, volume_id)

    def get_migrations(self, message, filters):
        return self.compute_api.get_migrations(message.ctxt, filters)

    def get_keypair_at_top(self, message, user_id, name):
        """Get keypair in API cells by name. Just return None if there is
        no match keypair.
        """
        if not self._at_the_top():
            return

        try:
            return objects.KeyPair.get_by_name(message.ctxt, user_id, name)
        except exception.KeypairNotFound:
            pass


_CELL_MESSAGE_TYPE_TO_MESSAGE_CLS = {'targeted': _TargetedMessage,
                                     'broadcast': _BroadcastMessage,
                                     'response': _ResponseMessage}
_CELL_MESSAGE_TYPE_TO_METHODS_CLS = {'targeted': _TargetedMessageMethods,
                                     'broadcast': _BroadcastMessageMethods,
                                     'response': _ResponseMessageMethods}


#
# Below are the public interfaces into this module.
#


class MessageRunner(object):
    """This class is the main interface into creating messages and
    processing them.

    Public methods in this class are typically called by the CellsManager
    to create a new message and process it with the exception of
    'message_from_json' which should be used by CellsDrivers to convert
    a JSONified message it has received back into the appropriate Message
    class.

    Private methods are used internally when we need to keep some
    'global' state.  For instance, eventlet queues used for responses are
    held in this class.  Also, when a Message is process()ed above and
    it's determined we should take action locally,
    _process_message_locally() will be called.

    When needing to add a new method to call in a Cell2Cell message,
    define the new method below and also add it to the appropriate
    MessageMethods class where the real work will be done.
    """

    def __init__(self, state_manager):
        self.state_manager = state_manager
        cells_scheduler_cls = importutils.import_class(
                CONF.cells.scheduler)
        self.scheduler = cells_scheduler_cls(self)
        self.response_queues = {}
        self.methods_by_type = {}
        self.our_name = CONF.cells.name
        for msg_type, cls in _CELL_MESSAGE_TYPE_TO_METHODS_CLS.items():
            self.methods_by_type[msg_type] = cls(self)
        self.serializer = objects_base.NovaObjectSerializer()

    def _process_message_locally(self, message):
        """Message processing will call this when its determined that
        the message should be processed within this cell.  Find the
        method to call based on the message type, and call it.  The
        caller is responsible for catching exceptions and returning
        results to cells, if needed.
        """
        methods = self.methods_by_type[message.message_type]
        fn = getattr(methods, message.method_name)
        return fn(message, **message.method_kwargs)

    def _put_response(self, response_uuid, response):
        """Put a response into a response queue.  This is called when
        a _ResponseMessage is processed in the cell that initiated a
        'call' to another cell.
        """
        resp_queue = self.response_queues.get(response_uuid)
        if not resp_queue:
            # Response queue is gone.  We must have restarted or we
            # received a response after our timeout period.
            return
        resp_queue.put(response)

    def _setup_response_queue(self, message):
        """Set up an eventlet queue to use to wait for replies.

        Replies come back from the target cell as a _ResponseMessage
        being sent back to the source.
        """
        resp_queue = queue.Queue()
        self.response_queues[message.uuid] = resp_queue
        return resp_queue

    def _cleanup_response_queue(self, message):
        """Stop tracking the response queue either because we're
        done receiving responses, or we've timed out.
        """
        try:
            del self.response_queues[message.uuid]
        except KeyError:
            # Ignore if queue is gone already somehow.
            pass

    def _create_response_message(self, ctxt, direction, target_cell,
            response_uuid, response_kwargs, **kwargs):
        """Create a ResponseMessage.  This is used internally within
        the nova.cells.messaging module.
        """
        return _ResponseMessage(self, ctxt, 'parse_responses',
                                response_kwargs, direction, target_cell,
                                response_uuid, **kwargs)

    def _get_migrations_for_cell(self, ctxt, cell_name, filters):
        method_kwargs = dict(filters=filters)
        message = _TargetedMessage(self, ctxt, 'get_migrations',
                                   method_kwargs, 'down', cell_name,
                                   need_response=True)

        response = message.process()
        if response.failure and isinstance(response.value[1],
                                           exception.CellRoutingInconsistency):
            return []

        return [response]

    def message_from_json(self, json_message):
        """Turns a message in JSON format into an appropriate Message
        instance.  This is called when cells receive a message from
        another cell.
        """
        message_dict = jsonutils.loads(json_message)
        # Need to convert context back.
        ctxt = message_dict['ctxt']
        message_dict['ctxt'] = context.RequestContext.from_dict(ctxt)
        # NOTE(comstud): We also need to re-serialize any objects that
        # exist in 'method_kwargs'.
        method_kwargs = message_dict['method_kwargs']
        for k, v in method_kwargs.items():
            method_kwargs[k] = self.serializer.deserialize_entity(
                    message_dict['ctxt'], v)
        message_type = message_dict.pop('message_type')
        message_cls = _CELL_MESSAGE_TYPE_TO_MESSAGE_CLS[message_type]
        return message_cls(self, **message_dict)

    def ask_children_for_capabilities(self, ctxt):
        """Tell child cells to send us capabilities.  This is typically
        called on startup of the nova-cells service.
        """
        child_cells = self.state_manager.get_child_cells()
        for child_cell in child_cells:
            message = _TargetedMessage(self, ctxt,
                                        'announce_capabilities',
                                        dict(), 'down', child_cell)
            message.process()

    def ask_children_for_capacities(self, ctxt):
        """Tell child cells to send us capacities.  This is typically
        called on startup of the nova-cells service.
        """
        child_cells = self.state_manager.get_child_cells()
        for child_cell in child_cells:
            message = _TargetedMessage(self, ctxt, 'announce_capacities',
                                        dict(), 'down', child_cell)
            message.process()

    def tell_parents_our_capabilities(self, ctxt):
        """Send our capabilities to parent cells."""
        parent_cells = self.state_manager.get_parent_cells()
        if not parent_cells:
            return
        my_cell_info = self.state_manager.get_my_state()
        capabs = self.state_manager.get_our_capabilities()
        parent_cell_names = ','.join(x.name for x in parent_cells)
        LOG.debug("Updating parents [%(parent_cell_names)s] with "
                                     "our capabilities: %(capabs)s",
                   {'parent_cell_names': parent_cell_names,
                    'capabs': capabs})
        # We have to turn the sets into lists so they can potentially
        # be json encoded when the raw message is sent.
        for key, values in capabs.items():
            capabs[key] = list(values)
        method_kwargs = {'cell_name': my_cell_info.name,
                         'capabilities': capabs}
        for cell in parent_cells:
            message = _TargetedMessage(self, ctxt, 'update_capabilities',
                    method_kwargs, 'up', cell, fanout=True)
            message.process()

    def tell_parents_our_capacities(self, ctxt):
        """Send our capacities to parent cells."""
        parent_cells = self.state_manager.get_parent_cells()
        if not parent_cells:
            return
        my_cell_info = self.state_manager.get_my_state()
        capacities = self.state_manager.get_our_capacities()
        parent_cell_names = ','.join(x.name for x in parent_cells)
        LOG.debug("Updating parents [%(parent_cell_names)s] with "
                                   "our capacities: %(capacities)s",
                  {'parent_cell_names': parent_cell_names,
                   'capacities': capacities})
        method_kwargs = {'cell_name': my_cell_info.name,
                         'capacities': capacities}
        for cell in parent_cells:
            message = _TargetedMessage(self, ctxt, 'update_capacities',
                    method_kwargs, 'up', cell, fanout=True)
            message.process()

    def build_instances(self, ctxt, target_cell, build_inst_kwargs):
        """Called by the cell scheduler to tell a child cell to build
        instance(s).
        """
        method_kwargs = dict(build_inst_kwargs=build_inst_kwargs)
        message = _TargetedMessage(self, ctxt, 'build_instances',
                                   method_kwargs, 'down', target_cell)
        message.process()

    def run_compute_api_method(self, ctxt, cell_name, method_info, call):
        """Call a compute API method in a specific cell."""
        message = _TargetedMessage(self, ctxt, 'run_compute_api_method',
                                   dict(method_info=method_info), 'down',
                                   cell_name, need_response=call)
        return message.process()

    def instance_update_at_top(self, ctxt, instance):
        """Update an instance at the top level cell."""
        message = _BroadcastMessage(self, ctxt, 'instance_update_at_top',
                                    dict(instance=instance), 'up',
                                    run_locally=False)
        message.process()

    def instance_destroy_at_top(self, ctxt, instance):
        """Destroy an instance at the top level cell."""
        message = _BroadcastMessage(self, ctxt, 'instance_destroy_at_top',
                                    dict(instance=instance), 'up',
                                    run_locally=False)
        message.process()

    def instance_delete_everywhere(self, ctxt, instance, delete_type):
        """This is used by API cell when it didn't know what cell
        an instance was in, but the instance was requested to be
        deleted or soft_deleted.  So, we'll broadcast this everywhere.
        """
        method_kwargs = dict(instance=instance, delete_type=delete_type)
        message = _BroadcastMessage(self, ctxt,
                                    'instance_delete_everywhere',
                                    method_kwargs, 'down',
                                    run_locally=False)
        message.process()

    def instance_fault_create_at_top(self, ctxt, instance_fault):
        """Create an instance fault at the top level cell."""
        message = _BroadcastMessage(self, ctxt,
                                    'instance_fault_create_at_top',
                                    dict(instance_fault=instance_fault),
                                    'up', run_locally=False)
        message.process()

    def bw_usage_update_at_top(self, ctxt, bw_update_info):
        """Update bandwidth usage at top level cell."""
        message = _BroadcastMessage(self, ctxt, 'bw_usage_update_at_top',
                                    dict(bw_update_info=bw_update_info),
                                    'up', run_locally=False)
        message.process()

    def sync_instances(self, ctxt, project_id, updated_since, deleted):
        """Force a sync of all instances, potentially by project_id,
        and potentially since a certain date/time.
        """
        method_kwargs = dict(project_id=project_id,
                             updated_since=updated_since,
                             deleted=deleted)
        message = _BroadcastMessage(self, ctxt, 'sync_instances',
                                    method_kwargs, 'down',
                                    run_locally=False)
        message.process()

    def service_get_all(self, ctxt, filters=None):
        method_kwargs = dict(filters=filters)
        message = _BroadcastMessage(self, ctxt, 'service_get_all',
                                    method_kwargs, 'down',
                                    run_locally=True, need_response=True)
        return message.process()

    def service_get_by_compute_host(self, ctxt, cell_name, host_name):
        method_kwargs = dict(host_name=host_name)
        message = _TargetedMessage(self, ctxt,
                                  'service_get_by_compute_host',
                                  method_kwargs, 'down', cell_name,
                                  need_response=True)
        return message.process()

    def get_host_uptime(self, ctxt, cell_name, host_name):
        method_kwargs = dict(host_name=host_name)
        message = _TargetedMessage(self, ctxt,
                                   'get_host_uptime',
                                   method_kwargs, 'down', cell_name,
                                   need_response=True)
        return message.process()

    def service_update(self, ctxt, cell_name, host_name, binary,
                       params_to_update):
        """Used to enable/disable a service. For compute services, setting to
        disabled stops new builds arriving on that host.

        :param host_name: the name of the host machine that the service is
                          running
        :param binary: The name of the executable that the service runs as
        :param params_to_update: eg. {'disabled': True}
        :returns: the update service object
        """
        method_kwargs = dict(host_name=host_name, binary=binary,
                             params_to_update=params_to_update)
        message = _TargetedMessage(self, ctxt,
                                  'service_update',
                                  method_kwargs, 'down', cell_name,
                                  need_response=True)
        return message.process()

    def service_delete(self, ctxt, cell_name, service_id):
        """Deletes the specified service."""
        method_kwargs = {'service_id': service_id}
        message = _TargetedMessage(self, ctxt,
                                   'service_delete',
                                   method_kwargs, 'down', cell_name,
                                   need_response=True)
        message.process()

    def proxy_rpc_to_manager(self, ctxt, cell_name, host_name, topic,
                             rpc_message, call, timeout):
        method_kwargs = {'host_name': host_name,
                         'topic': topic,
                         'rpc_message': rpc_message,
                         'timeout': timeout}
        message = _TargetedMessage(self, ctxt,
                                   'proxy_rpc_to_manager',
                                   method_kwargs, 'down', cell_name,
                                   need_response=call)
        return message.process()

    def task_log_get_all(self, ctxt, cell_name, task_name,
                         period_beginning, period_ending,
                         host=None, state=None):
        """Get task logs from the DB from all cells or a particular
        cell.

        If 'cell_name' is None or '', get responses from all cells.
        If 'host' is not None, filter by host.
        If 'state' is not None, filter by state.

        Return a list of Response objects.
        """
        method_kwargs = dict(task_name=task_name,
                             period_beginning=period_beginning,
                             period_ending=period_ending,
                             host=host, state=state)
        if cell_name:
            message = _TargetedMessage(self, ctxt, 'task_log_get_all',
                                    method_kwargs, 'down',
                                    cell_name, need_response=True)
            # Caller should get a list of Responses.
            return [message.process()]
        message = _BroadcastMessage(self, ctxt, 'task_log_get_all',
                                    method_kwargs, 'down',
                                    run_locally=True, need_response=True)
        return message.process()

    def compute_node_get_all(self, ctxt, hypervisor_match=None):
        """Return list of compute nodes in all child cells."""
        method_kwargs = dict(hypervisor_match=hypervisor_match)
        message = _BroadcastMessage(self, ctxt, 'compute_node_get_all',
                                    method_kwargs, 'down',
                                    run_locally=True, need_response=True)
        return message.process()

    def compute_node_stats(self, ctxt):
        """Return compute node stats from all child cells."""
        method_kwargs = dict()
        message = _BroadcastMessage(self, ctxt, 'compute_node_stats',
                                    method_kwargs, 'down',
                                    run_locally=True, need_response=True)
        return message.process()

    def compute_node_get(self, ctxt, cell_name, compute_id):
        """Return compute node entry from a specific cell by ID or UUID."""
        method_kwargs = dict(compute_id=compute_id)
        message = _TargetedMessage(self, ctxt, 'compute_node_get',
                                    method_kwargs, 'down',
                                    cell_name, need_response=True)
        return message.process()

    def actions_get(self, ctxt, cell_name, instance_uuid):
        method_kwargs = dict(instance_uuid=instance_uuid)
        message = _TargetedMessage(self, ctxt, 'actions_get',
                                method_kwargs, 'down',
                                cell_name, need_response=True)
        return message.process()

    def action_get_by_request_id(self, ctxt, cell_name, instance_uuid,
                                 request_id):
        method_kwargs = dict(instance_uuid=instance_uuid,
                             request_id=request_id)
        message = _TargetedMessage(self, ctxt, 'action_get_by_request_id',
                                method_kwargs, 'down',
                                cell_name, need_response=True)
        return message.process()

    def action_events_get(self, ctxt, cell_name, action_id):
        method_kwargs = dict(action_id=action_id)
        message = _TargetedMessage(self, ctxt, 'action_events_get',
                                method_kwargs, 'down',
                                cell_name, need_response=True)
        return message.process()

    def consoleauth_delete_tokens(self, ctxt, instance_uuid):
        """Delete consoleauth tokens for an instance in API cells."""
        message = _BroadcastMessage(self, ctxt, 'consoleauth_delete_tokens',
                                    dict(instance_uuid=instance_uuid),
                                    'up', run_locally=False)
        message.process()

    def validate_console_port(self, ctxt, cell_name, instance_uuid,
                              console_port, console_type):
        """Validate console port with child cell compute node."""
        method_kwargs = {'instance_uuid': instance_uuid,
                         'console_port': console_port,
                         'console_type': console_type}
        message = _TargetedMessage(self, ctxt, 'validate_console_port',
                                   method_kwargs, 'down',
                                   cell_name, need_response=True)
        return message.process()

    def bdm_update_or_create_at_top(self, ctxt, bdm, create=None):
        """Update/Create a BDM at top level cell."""
        message = _BroadcastMessage(self, ctxt,
                                    'bdm_update_or_create_at_top',
                                    dict(bdm=bdm, create=create),
                                    'up', run_locally=False)
        message.process()

    def bdm_destroy_at_top(self, ctxt, instance_uuid, device_name=None,
                           volume_id=None):
        """Destroy a BDM at top level cell."""
        method_kwargs = dict(instance_uuid=instance_uuid,
                             device_name=device_name,
                             volume_id=volume_id)
        message = _BroadcastMessage(self, ctxt, 'bdm_destroy_at_top',
                                    method_kwargs,
                                    'up', run_locally=False)
        message.process()

    def get_migrations(self, ctxt, cell_name, run_locally, filters):
        """Fetch all migrations applying the filters for a given cell or all
        cells.
        """
        method_kwargs = dict(filters=filters)
        if cell_name:
            return self._get_migrations_for_cell(ctxt, cell_name, filters)

        message = _BroadcastMessage(self, ctxt, 'get_migrations',
                                    method_kwargs, 'down',
                                    run_locally=run_locally,
                                    need_response=True)
        return message.process()

    def _instance_action(self, ctxt, instance, method, extra_kwargs=None,
                         need_response=False):
        """Call instance_<method> in correct cell for instance."""
        cell_name = instance.cell_name
        if not cell_name:
            LOG.warning("No cell_name for %(method)s() from API",
                        dict(method=method), instance=instance)
            return
        method_kwargs = {'instance': instance}
        if extra_kwargs:
            method_kwargs.update(extra_kwargs)
        message = _TargetedMessage(self, ctxt, method, method_kwargs,
                                   'down', cell_name,
                                   need_response=need_response)
        return message.process()

    def instance_update_from_api(self, ctxt, instance,
                                expected_vm_state, expected_task_state,
                                admin_state_reset):
        """Update an instance object in its cell."""
        cell_name = instance.cell_name
        if not cell_name:
            LOG.warning("No cell_name for instance update from API",
                        instance=instance)
            return
        method_kwargs = {'instance': instance,
                         'expected_vm_state': expected_vm_state,
                         'expected_task_state': expected_task_state,
                         'admin_state_reset': admin_state_reset}
        message = _TargetedMessage(self, ctxt, 'instance_update_from_api',
                                   method_kwargs, 'down',
                                   cell_name)
        message.process()

    def start_instance(self, ctxt, instance):
        """Start an instance in its cell."""
        self._instance_action(ctxt, instance, 'start_instance')

    def stop_instance(self, ctxt, instance, do_cast=True, clean_shutdown=True):
        """Stop an instance in its cell."""
        extra_kwargs = dict(clean_shutdown=clean_shutdown)
        if do_cast:
            self._instance_action(ctxt, instance, 'stop_instance',
                                  extra_kwargs=extra_kwargs)
        else:
            return self._instance_action(ctxt, instance, 'stop_instance',
                                         extra_kwargs=extra_kwargs,
                                         need_response=True)

    def reboot_instance(self, ctxt, instance, reboot_type):
        """Reboot an instance in its cell."""
        extra_kwargs = dict(reboot_type=reboot_type)
        self._instance_action(ctxt, instance, 'reboot_instance',
                              extra_kwargs=extra_kwargs)

    def suspend_instance(self, ctxt, instance):
        """Suspend an instance in its cell."""
        self._instance_action(ctxt, instance, 'suspend_instance')

    def resume_instance(self, ctxt, instance):
        """Resume an instance in its cell."""
        self._instance_action(ctxt, instance, 'resume_instance')

    def terminate_instance(self, ctxt, instance, delete_type='delete'):
        extra_kwargs = dict(delete_type=delete_type)
        self._instance_action(ctxt, instance, 'terminate_instance',
                              extra_kwargs=extra_kwargs)

    def soft_delete_instance(self, ctxt, instance):
        self._instance_action(ctxt, instance, 'soft_delete_instance')

    def pause_instance(self, ctxt, instance):
        """Pause an instance in its cell."""
        self._instance_action(ctxt, instance, 'pause_instance')

    def unpause_instance(self, ctxt, instance):
        """Unpause an instance in its cell."""
        self._instance_action(ctxt, instance, 'unpause_instance')

    def resize_instance(self, ctxt, instance, flavor,
                       extra_instance_updates,
                       clean_shutdown=True):
        """Resize an instance in its cell."""
        extra_kwargs = dict(flavor=flavor,
                            extra_instance_updates=extra_instance_updates,
                            clean_shutdown=clean_shutdown)
        self._instance_action(ctxt, instance, 'resize_instance',
                              extra_kwargs=extra_kwargs)

    def live_migrate_instance(self, ctxt, instance, block_migration,
                              disk_over_commit, host_name):
        """Live migrate an instance in its cell."""
        extra_kwargs = dict(block_migration=block_migration,
                            disk_over_commit=disk_over_commit,
                            host_name=host_name)
        self._instance_action(ctxt, instance, 'live_migrate_instance',
                              extra_kwargs=extra_kwargs)

    def revert_resize(self, ctxt, instance):
        """Revert a resize for an instance in its cell."""
        self._instance_action(ctxt, instance, 'revert_resize')

    def confirm_resize(self, ctxt, instance):
        """Confirm a resize for an instance in its cell."""
        self._instance_action(ctxt, instance, 'confirm_resize')

    def reset_network(self, ctxt, instance):
        """Reset networking for an instance in its cell."""
        self._instance_action(ctxt, instance, 'reset_network')

    def inject_network_info(self, ctxt, instance):
        """Inject networking for an instance in its cell."""
        self._instance_action(ctxt, instance, 'inject_network_info')

    def snapshot_instance(self, ctxt, instance, image_id):
        """Snapshot an instance in its cell."""
        extra_kwargs = dict(image_id=image_id)
        self._instance_action(ctxt, instance, 'snapshot_instance',
                              extra_kwargs=extra_kwargs)

    def backup_instance(self, ctxt, instance, image_id, backup_type,
                        rotation):
        """Backup an instance in its cell."""
        extra_kwargs = dict(image_id=image_id, backup_type=backup_type,
                            rotation=rotation)
        self._instance_action(ctxt, instance, 'backup_instance',
                              extra_kwargs=extra_kwargs)

    def rebuild_instance(self, ctxt, instance, image_href, admin_password,
                         files_to_inject, preserve_ephemeral, kwargs):
        extra_kwargs = dict(image_href=image_href,
                            admin_password=admin_password,
                            files_to_inject=files_to_inject,
                            preserve_ephemeral=preserve_ephemeral,
                            kwargs=kwargs)
        self._instance_action(ctxt, instance, 'rebuild_instance',
                              extra_kwargs=extra_kwargs)

    def set_admin_password(self, ctxt, instance, new_pass):
        self._instance_action(ctxt, instance, 'set_admin_password',
                extra_kwargs={'new_pass': new_pass})

    def get_keypair_at_top(self, ctxt, user_id, name):
        """Get Key Pair by name at top level cell."""
        message = _BroadcastMessage(self, ctxt,
                                    'get_keypair_at_top',
                                    dict(user_id=user_id, name=name),
                                    'up',
                                    need_response=True, run_locally=False)
        return message.process()

    @staticmethod
    def get_message_types():
        return _CELL_MESSAGE_TYPE_TO_MESSAGE_CLS.keys()


class Response(object):
    """Holds a response from a cell.  If there was a failure, 'failure'
    will be True and 'response' will contain an encoded Exception.
    """
    def __init__(self, ctxt, cell_name, value, failure):
        self.failure = failure
        self.cell_name = cell_name
        self.value = value
        self.ctxt = ctxt
        self.serializer = objects_base.NovaObjectSerializer()

    def to_json(self):
        resp_value = self.serializer.serialize_entity(self.ctxt, self.value)
        if self.failure:
            resp_value = serialize_remote_exception(resp_value,
                                                    log_failure=False)
        _dict = {'cell_name': self.cell_name,
                 'value': resp_value,
                 'failure': self.failure}
        return jsonutils.dumps(_dict)

    @classmethod
    def from_json(cls, ctxt, json_message):
        _dict = jsonutils.loads(json_message)
        if _dict['failure']:
            resp_value = deserialize_remote_exception(_dict['value'],
                                                      rpc.get_allowed_exmods())
            _dict['value'] = resp_value
        response = cls(ctxt, **_dict)
        response.value = response.serializer.deserialize_entity(
            response.ctxt, response.value)
        return response

    def value_or_raise(self):
        if self.failure:
            if isinstance(self.value, (tuple, list)):
                six.reraise(*self.value)
            else:
                raise self.value
        return self.value


_REMOTE_POSTFIX = '_Remote'


def serialize_remote_exception(failure_info, log_failure=True):
    """Prepares exception data to be sent over rpc.

    Failure_info should be a sys.exc_info() tuple.

    """
    tb = traceback.format_exception(*failure_info)
    failure = failure_info[1]
    if log_failure:
        LOG.error("Returning exception %s to caller",
                  six.text_type(failure))
        LOG.error(tb)

    kwargs = {}
    if hasattr(failure, 'kwargs'):
        kwargs = failure.kwargs

    # NOTE(matiu): With cells, it's possible to re-raise remote, remote
    # exceptions. Lets turn it back into the original exception type.
    cls_name = str(failure.__class__.__name__)
    mod_name = str(failure.__class__.__module__)
    if (cls_name.endswith(_REMOTE_POSTFIX) and
            mod_name.endswith(_REMOTE_POSTFIX)):
        cls_name = cls_name[:-len(_REMOTE_POSTFIX)]
        mod_name = mod_name[:-len(_REMOTE_POSTFIX)]

    data = {
        'class': cls_name,
        'module': mod_name,
        'message': six.text_type(failure),
        'tb': tb,
        'args': failure.args,
        'kwargs': kwargs
    }

    json_data = jsonutils.dumps(data)

    return json_data


def deserialize_remote_exception(data, allowed_remote_exmods):
    failure = jsonutils.loads(str(data))

    trace = failure.get('tb', [])
    message = failure.get('message', "") + "\n" + "\n".join(trace)
    name = failure.get('class')
    module = failure.get('module')

    # NOTE(ameade): We DO NOT want to allow just any module to be imported, in
    # order to prevent arbitrary code execution.
    if module != 'exceptions' and module not in allowed_remote_exmods:
        return messaging.RemoteError(name, failure.get('message'), trace)

    try:
        mod = importutils.import_module(module)
        klass = getattr(mod, name)
        if not issubclass(klass, Exception):
            raise TypeError("Can only deserialize Exceptions")

        failure = klass(*failure.get('args', []), **failure.get('kwargs', {}))
    except (AttributeError, TypeError, ImportError):
        return messaging.RemoteError(name, failure.get('message'), trace)

    ex_type = type(failure)
    str_override = lambda self: message
    new_ex_type = type(ex_type.__name__ + _REMOTE_POSTFIX, (ex_type,),
                       {'__str__': str_override, '__unicode__': str_override})
    new_ex_type.__module__ = '%s%s' % (module, _REMOTE_POSTFIX)
    try:
        # NOTE(ameade): Dynamically create a new exception type and swap it in
        # as the new type for the exception. This only works on user defined
        # Exceptions and not core python exceptions. This is important because
        # we cannot necessarily change an exception message so we must override
        # the __str__ method.
        failure.__class__ = new_ex_type
    except TypeError:
        # NOTE(ameade): If a core exception then just add the traceback to the
        # first exception argument.
        failure.args = (message,) + failure.args[1:]
    return failure
