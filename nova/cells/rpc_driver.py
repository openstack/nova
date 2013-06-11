# Copyright (c) 2012 Rackspace Hosting
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

"""
Cells RPC Communication Driver
"""
from oslo.config import cfg

from nova.cells import driver
from nova.openstack.common import rpc
from nova.openstack.common.rpc import dispatcher as rpc_dispatcher
from nova.openstack.common.rpc import proxy as rpc_proxy

cell_rpc_driver_opts = [
        cfg.StrOpt('rpc_driver_queue_base',
                   default='cells.intercell',
                   help="Base queue name to use when communicating between "
                        "cells.  Various topics by message type will be "
                        "appended to this.")]

CONF = cfg.CONF
CONF.register_opts(cell_rpc_driver_opts, group='cells')
CONF.import_opt('call_timeout', 'nova.cells.opts', group='cells')

rpcapi_cap_opt = cfg.StrOpt('intercell',
        default=None,
        help='Set a version cap for messages sent between cells services')
CONF.register_opt(rpcapi_cap_opt, 'upgrade_levels')

_CELL_TO_CELL_RPC_API_VERSION = '1.0'


class CellsRPCDriver(driver.BaseCellsDriver):
    """Driver for cell<->cell communication via RPC.  This is used to
    setup the RPC consumers as well as to send a message to another cell.

    One instance of this class will be created for every neighbor cell
    that we find in the DB and it will be associated with the cell in
    its CellState.

    One instance is also created by the cells manager for setting up
    the consumers.
    """
    BASE_RPC_API_VERSION = _CELL_TO_CELL_RPC_API_VERSION

    def __init__(self, *args, **kwargs):
        super(CellsRPCDriver, self).__init__(*args, **kwargs)
        self.rpc_connections = []
        self.intercell_rpcapi = InterCellRPCAPI(
                self.BASE_RPC_API_VERSION)

    def _start_consumer(self, dispatcher, topic):
        """Start an RPC consumer."""
        conn = rpc.create_connection(new=True)
        conn.create_consumer(topic, dispatcher, fanout=False)
        conn.create_consumer(topic, dispatcher, fanout=True)
        self.rpc_connections.append(conn)
        conn.consume_in_thread()
        return conn

    def start_consumers(self, msg_runner):
        """Start RPC consumers.

        Start up 2 separate consumers for handling inter-cell
        communication via RPC.  Both handle the same types of
        messages, but requests/replies are separated to solve
        potential deadlocks. (If we used the same queue for both,
        it's possible to exhaust the RPC thread pool while we wait
        for replies.. such that we'd never consume a reply.)
        """
        topic_base = CONF.cells.rpc_driver_queue_base
        proxy_manager = InterCellRPCDispatcher(msg_runner)
        dispatcher = rpc_dispatcher.RpcDispatcher([proxy_manager])
        for msg_type in msg_runner.get_message_types():
            topic = '%s.%s' % (topic_base, msg_type)
            self._start_consumer(dispatcher, topic)

    def stop_consumers(self):
        """Stop RPC consumers.

        NOTE: Currently there's no hooks when stopping services
        to have managers cleanup, so this is not currently called.
        """
        for conn in self.rpc_connections:
            conn.close()

    def send_message_to_cell(self, cell_state, message):
        """Use the IntercellRPCAPI to send a message to a cell."""
        self.intercell_rpcapi.send_message_to_cell(cell_state, message)


class InterCellRPCAPI(rpc_proxy.RpcProxy):
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

    def __init__(self, default_version):
        version_cap = self.VERSION_ALIASES.get(CONF.upgrade_levels.intercell,
                                               CONF.upgrade_levels.intercell)
        super(InterCellRPCAPI, self).__init__(None, default_version,
                version_cap=version_cap)

    @staticmethod
    def _get_server_params_for_cell(next_hop):
        """Turn the DB information for a cell into the parameters
        needed for the RPC call.
        """
        param_map = {'username': 'username',
                     'password': 'password',
                     'rpc_host': 'hostname',
                     'rpc_port': 'port',
                     'rpc_virtual_host': 'virtual_host'}
        server_params = {}
        for source, target in param_map.items():
            if next_hop.db_info[source]:
                server_params[target] = next_hop.db_info[source]
        return server_params

    def send_message_to_cell(self, cell_state, message):
        """Send a message to another cell by JSON-ifying the message and
        making an RPC cast to 'process_message'.  If the message says to
        fanout, do it.  The topic that is used will be
        'CONF.rpc_driver_queue_base.<message_type>'.
        """
        ctxt = message.ctxt
        json_message = message.to_json()
        rpc_message = self.make_msg('process_message', message=json_message)
        topic_base = CONF.cells.rpc_driver_queue_base
        topic = '%s.%s' % (topic_base, message.message_type)
        server_params = self._get_server_params_for_cell(cell_state)
        if message.fanout:
            self.fanout_cast_to_server(ctxt, server_params,
                    rpc_message, topic=topic)
        else:
            self.cast_to_server(ctxt, server_params,
                    rpc_message, topic=topic)


class InterCellRPCDispatcher(object):
    """RPC Dispatcher to handle messages received from other cells.

    All messages received here have come from a sibling cell.  Depending
    on the ultimate target and type of message, we may process the message
    in this cell, relay the message to another sibling cell, or both.  This
    logic is defined by the message class in the messaging module.
    """
    BASE_RPC_API_VERSION = _CELL_TO_CELL_RPC_API_VERSION

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
