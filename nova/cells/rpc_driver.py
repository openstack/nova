# Copyright (c) 2012 Rackspace Hosting
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
Cells RPC Communication Driver
"""
import oslo_messaging as messaging

from nova.cells import driver
import nova.conf
from nova import rpc


CONF = nova.conf.CONF


class CellsRPCDriver(driver.BaseCellsDriver):
    """Driver for cell<->cell communication via RPC.  This is used to
    setup the RPC consumers as well as to send a message to another cell.

    One instance of this class will be created for every neighbor cell
    that we find in the DB and it will be associated with the cell in
    its CellState.

    One instance is also created by the cells manager for setting up
    the consumers.
    """

    def __init__(self, *args, **kwargs):
        super(CellsRPCDriver, self).__init__(*args, **kwargs)
        self.rpc_servers = []
        self.intercell_rpcapi = InterCellRPCAPI()

    def start_servers(self, msg_runner):
        """Start RPC servers.

        Start up 2 separate servers for handling inter-cell
        communication via RPC.  Both handle the same types of
        messages, but requests/replies are separated to solve
        potential deadlocks. (If we used the same queue for both,
        it's possible to exhaust the RPC thread pool while we wait
        for replies.. such that we'd never consume a reply.)
        """
        topic_base = CONF.cells.rpc_driver_queue_base
        proxy_manager = InterCellRPCDispatcher(msg_runner)
        for msg_type in msg_runner.get_message_types():
            target = messaging.Target(topic='%s.%s' % (topic_base, msg_type),
                                      server=CONF.host)
            # NOTE(comstud): We do not need to use the object serializer
            # on this because object serialization is taken care for us in
            # the nova.cells.messaging module.
            server = rpc.get_server(target, endpoints=[proxy_manager])
            server.start()
            self.rpc_servers.append(server)

    def stop_servers(self):
        """Stop RPC servers.

        NOTE: Currently there's no hooks when stopping services
        to have managers cleanup, so this is not currently called.
        """
        for server in self.rpc_servers:
            server.stop()

    def send_message_to_cell(self, cell_state, message):
        """Use the IntercellRPCAPI to send a message to a cell."""
        self.intercell_rpcapi.send_message_to_cell(cell_state, message)


class InterCellRPCAPI(object):
    """Client side of the Cell<->Cell RPC API.

    The CellsRPCDriver uses this to make calls to another cell.

    API version history:
        1.0 - Initial version.

        ... Grizzly supports message version 1.0.  So, any changes to existing
        methods in 2.x after that point should be done such that they can
        handle the version_cap being set to 1.0.
    """

    VERSION_ALIASES = {
        'grizzly': '1.0',
    }

    def __init__(self):
        super(InterCellRPCAPI, self).__init__()
        self.version_cap = (
            self.VERSION_ALIASES.get(CONF.upgrade_levels.intercell,
                                     CONF.upgrade_levels.intercell))
        self.transports = {}

    def _get_client(self, next_hop, topic):
        """Turn the DB information for a cell into a messaging.RPCClient."""
        transport = self._get_transport(next_hop)
        target = messaging.Target(topic=topic, version='1.0')
        serializer = rpc.RequestContextSerializer(None)
        return messaging.RPCClient(transport,
                                   target,
                                   version_cap=self.version_cap,
                                   serializer=serializer)

    def _get_transport(self, next_hop):
        """NOTE(belliott) Each Transport object contains connection pool
        state.  Maintain references to them to avoid continual reconnects
        to the message broker.
        """
        transport_url = next_hop.db_info['transport_url']
        if transport_url not in self.transports:
            transport = messaging.get_transport(nova.conf.CONF, transport_url,
                                                rpc.TRANSPORT_ALIASES)
            self.transports[transport_url] = transport
        else:
            transport = self.transports[transport_url]

        return transport

    def send_message_to_cell(self, cell_state, message):
        """Send a message to another cell by JSON-ifying the message and
        making an RPC cast to 'process_message'.  If the message says to
        fanout, do it.  The topic that is used will be
        'CONF.rpc_driver_queue_base.<message_type>'.
        """
        topic_base = CONF.cells.rpc_driver_queue_base
        topic = '%s.%s' % (topic_base, message.message_type)
        cctxt = self._get_client(cell_state, topic)
        if message.fanout:
            cctxt = cctxt.prepare(fanout=message.fanout)
        return cctxt.cast(message.ctxt, 'process_message',
                          message=message.to_json())


class InterCellRPCDispatcher(object):
    """RPC Dispatcher to handle messages received from other cells.

    All messages received here have come from a sibling cell.  Depending
    on the ultimate target and type of message, we may process the message
    in this cell, relay the message to another sibling cell, or both.  This
    logic is defined by the message class in the nova.cells.messaging module.
    """

    target = messaging.Target(version='1.0')

    def __init__(self, msg_runner):
        """Init the Intercell RPC Dispatcher."""
        self.msg_runner = msg_runner

    def process_message(self, _ctxt, message):
        """We received a message from another cell.  Use the MessageRunner
        to turn this from JSON back into an instance of the correct
        Message class.  Then process it!
        """
        message = self.msg_runner.message_from_json(message)
        message.process()
