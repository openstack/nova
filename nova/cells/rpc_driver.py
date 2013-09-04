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
import urllib
import urlparse

from oslo.config import cfg

from nova.cells import driver
from nova.openstack.common.gettextutils import _
from nova.openstack.common import rpc
from nova.openstack.common.rpc import dispatcher as rpc_dispatcher
from nova import rpcclient

cell_rpc_driver_opts = [
        cfg.StrOpt('rpc_driver_queue_base',
                   default='cells.intercell',
                   help="Base queue name to use when communicating between "
                        "cells.  Various topics by message type will be "
                        "appended to this.")]

CONF = cfg.CONF
CONF.register_opts(cell_rpc_driver_opts, group='cells')
CONF.import_opt('call_timeout', 'nova.cells.opts', group='cells')
CONF.import_opt('rpc_backend', 'nova.openstack.common.rpc')

rpcapi_cap_opt = cfg.StrOpt('intercell',
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
        # NOTE(comstud): We do not need to use the object serializer
        # on this because object serialization is taken care for us in
        # the messaging module.
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


class InterCellRPCAPI(rpcclient.RpcProxy):
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

    def _get_client(self, next_hop, topic):
        server_params = self._get_server_params_for_cell(next_hop)
        cctxt = self.get_client(server_params=server_params)
        return cctxt.prepare(topic=topic)

    @staticmethod
    def _get_server_params_for_cell(next_hop):
        """Turn the DB information for a cell into the parameters
        needed for the RPC call.
        """
        server_params = parse_transport_url(next_hop.db_info['transport_url'])

        return dict((k, v) for k, v in server_params.items() if v)

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


def parse_transport_url(url):
    """
    Parse a transport URL.

    :param url: The transport URL.

    :returns: A dictionary of 5 elements: the "username", the
              "password", the "hostname", the "port" (as an integer),
              and the "virtual_host" for the requested transport.
    """

    # TODO(Vek): Use the actual Oslo code, once it lands in
    # oslo-incubator

    # First step is to parse the URL
    parsed = urlparse.urlparse(url or '')

    # Make sure we understand the scheme
    if parsed.scheme not in ('rabbit', 'qpid'):
        raise ValueError(_("Unable to handle transport URL scheme %s") %
                         parsed.scheme)

    # Make sure there's not a query string; that could identify
    # requirements we can't comply with (e.g., ssl), so reject it if
    # it's present
    if '?' in parsed.path or parsed.query:
        raise ValueError(_("Cannot comply with query string in transport URL"))

    # Extract the interesting information from the URL; this requires
    # dequoting values, and ensuring empty values become None
    username = urllib.unquote(parsed.username) if parsed.username else None
    password = urllib.unquote(parsed.password) if parsed.password else None
    virtual_host = urllib.unquote(parsed.path[1:]) or None

    # Now we have to extract the hostname and port; unfortunately,
    # urlparse in Python 2.6 doesn't understand IPv6 addresses
    hostname = parsed.hostname
    if hostname and hostname[0] == '[':
        # If '@' is present, rfind() finds its position; if it isn't,
        # rfind() returns -1.  Either way, adding 1 gives us the start
        # location of the host and port...
        host_start = parsed.netloc.rfind('@')
        netloc = parsed.netloc[host_start + 1:]

        # Find the closing ']' and extract the hostname
        host_end = netloc.find(']')
        if host_end < 0:
            # NOTE(Vek): Not translated so it's identical to what
            # Python 2.7's urlparse.urlparse() raises in this case
            raise ValueError("Invalid IPv6 URL")
        hostname = netloc[1:host_end]

        # Now we need the port; this is compliant with how urlparse
        # parses the port data
        port_text = netloc[host_end:]
        port = None
        if ':' in port_text:
            port = int(port_text.split(':', 1)[1])
    else:
        port = parsed.port

    # Now that we have what we need, return the information
    return {
        'username': username,
        'password': password,
        'hostname': hostname,
        'port': port,
        'virtual_host': virtual_host,
    }


def unparse_transport_url(transport, secure=True):
    """
    Unparse a transport URL; that is, synthesize a transport URL from
    a dictionary similar to that one returned by
    parse_transport_url().

    :param transport: The dictionary containing the transport URL
                      components.
    :param secure: Used to identify whether the transport URL is
                   wanted for a secure or insecure link.  If
                   True--indicating a secure link--the password will
                   be included; otherwise, it won't.

    :returns: The transport URL.
    """

    # Starting place for the network location
    netloc = ''

    # Extract all the data we need from the dictionary
    username = transport.get('username')
    if secure:
        password = transport.get('password')
    else:
        password = None
    hostname = transport.get('hostname')
    port = transport.get('port')
    virtual_host = transport.get('virtual_host')

    # Build the username and password portion of the transport URL
    if username or password:
        if username:
            netloc += urllib.quote(username, '')
        if password:
            netloc += ':%s' % urllib.quote(password, '')
        netloc += '@'

    # Build the network location portion of the transport URL
    if hostname:
        if ':' in hostname:
            # Encode an IPv6 address properly
            netloc += "[%s]" % hostname
        else:
            netloc += hostname
    if port is not None:
        netloc += ":%d" % port

    # Determine the scheme
    # NOTE(Vek): This isn't really that robust, but should be more
    #            than sufficient to carry us on until the more
    #            complete transition to transport URLs can be
    #            accomplished.
    if CONF.rpc_backend.endswith('qpid'):
        scheme = 'qpid'
    else:
        scheme = 'rabbit'

    # Assemble the transport URL
    url = "%s://%s/" % (scheme, netloc)
    if virtual_host:
        url += urllib.quote(virtual_host, '')

    return url
