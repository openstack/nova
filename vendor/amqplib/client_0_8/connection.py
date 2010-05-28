"""
AMQP 0-8 Connections

"""
# Copyright (C) 2007-2008 Barry Pederson <bp@barryp.org>
#
# This library is free software; you can redistribute it and/or
# modify it under the terms of the GNU Lesser General Public
# License as published by the Free Software Foundation; either
# version 2.1 of the License, or (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public
# License along with this library; if not, write to the Free Software
# Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301

import logging

from abstract_channel import AbstractChannel
from channel import Channel
from exceptions import *
from method_framing import MethodReader, MethodWriter
from serialization import AMQPReader, AMQPWriter
from transport import create_transport

__all__ =  [
            'Connection',
           ]

#
# Client property info that gets sent to the server on connection startup
#
LIBRARY_PROPERTIES = {
    'library': 'Python amqplib',
    'library_version': '0.6.1',
    }

AMQP_LOGGER = logging.getLogger('amqplib')


class Connection(AbstractChannel):
    """
    The connection class provides methods for a client to establish a
    network connection to a server, and for both peers to operate the
    connection thereafter.

    GRAMMAR:

        connection          = open-connection *use-connection close-connection
        open-connection     = C:protocol-header
                              S:START C:START-OK
                              *challenge
                              S:TUNE C:TUNE-OK
                              C:OPEN S:OPEN-OK | S:REDIRECT
        challenge           = S:SECURE C:SECURE-OK
        use-connection      = *channel
        close-connection    = C:CLOSE S:CLOSE-OK
                            / S:CLOSE C:CLOSE-OK

    """
    def __init__(self,
        host='localhost',
        userid='guest',
        password='guest',
        login_method='AMQPLAIN',
        login_response=None,
        virtual_host='/',
        locale='en_US',
        client_properties=None,
        ssl=False,
        insist=False,
        connect_timeout=None,
        **kwargs):
        """
        Create a connection to the specified host, which should be
        a 'host[:port]', such as 'localhost', or '1.2.3.4:5672'
        (defaults to 'localhost', if a port is not specified then
        5672 is used)

        If login_response is not specified, one is built up for you from
        userid and password if they are present.

        """
        if (login_response is None) \
        and (userid is not None) \
        and (password is not None):
            login_response = AMQPWriter()
            login_response.write_table({'LOGIN': userid, 'PASSWORD': password})
            login_response = login_response.getvalue()[4:]  #Skip the length
                                                            #at the beginning

        d = {}
        d.update(LIBRARY_PROPERTIES)
        if client_properties:
            d.update(client_properties)

        self.known_hosts = ''

        while True:
            self.channels = {}
            # The connection object itself is treated as channel 0
            super(Connection, self).__init__(self, 0)

            self.transport = None

            # Properties set in the Tune method
            self.channel_max = 65535
            self.frame_max = 131072
            self.heartbeat = 0

            # Properties set in the Start method
            self.version_major = 0
            self.version_minor = 0
            self.server_properties = {}
            self.mechanisms = []
            self.locales = []

            # Let the transport.py module setup the actual
            # socket connection to the broker.
            #
            self.transport = create_transport(host, connect_timeout, ssl)

            self.method_reader = MethodReader(self.transport)
            self.method_writer = MethodWriter(self.transport, self.frame_max)

            self.wait(allowed_methods=[
                    (10, 10), # start
                    ])

            self._x_start_ok(d, login_method, login_response, locale)

            self._wait_tune_ok = True
            while self._wait_tune_ok:
                self.wait(allowed_methods=[
                    (10, 20), # secure
                    (10, 30), # tune
                    ])

            host = self._x_open(virtual_host, insist=insist)
            if host is None:
                # we weren't redirected
                return

            # we were redirected, close the socket, loop and try again
            try:
                self.close()
            except Exception:
                pass


    def _do_close(self):
        self.transport.close()
        self.transport = None

        temp_list = [x for x in self.channels.values() if x is not self]
        for ch in temp_list:
            ch._do_close()

        self.connection = self.channels = None


    def _get_free_channel_id(self):
        for i in xrange(1, self.channel_max+1):
            if i not in self.channels:
                return i
        raise AMQPException('No free channel ids, current=%d, channel_max=%d'
            % (len(self.channels), self.channel_max))


    def _wait_method(self, channel_id, allowed_methods):
        """
        Wait for a method from the server destined for
        a particular channel.

        """
        #
        # Check the channel's deferred methods
        #
        method_queue = self.channels[channel_id].method_queue

        for queued_method in method_queue:
            method_sig = queued_method[0]
            if (allowed_methods is None) \
            or (method_sig in allowed_methods) \
            or (method_sig == (20, 40)):
                method_queue.remove(queued_method)
                return queued_method

        #
        # Nothing queued, need to wait for a method from the peer
        #
        while True:
            channel, method_sig, args, content = \
                self.method_reader.read_method()

            if (channel == channel_id) \
            and ((allowed_methods is None) \
                or (method_sig in allowed_methods) \
                or (method_sig == (20, 40))):
                return method_sig, args, content

            #
            # Not the channel and/or method we were looking for.  Queue
            # this method for later
            #
            self.channels[channel].method_queue.append((method_sig, args, content))

            #
            # If we just queued up a method for channel 0 (the Connection
            # itself) it's probably a close method in reaction to some
            # error, so deal with it right away.
            #
            if channel == 0:
                self.wait()


    def channel(self, channel_id=None):
        """
        Fetch a Channel object identified by the numeric channel_id, or
        create that object if it doesn't already exist.

        """
        if channel_id in self.channels:
            return self.channels[channel_id]

        return Channel(self, channel_id)


    #################

    def close(self, reply_code=0, reply_text='', method_sig=(0, 0)):
        """
        request a connection close

        This method indicates that the sender wants to close the
        connection. This may be due to internal conditions (e.g. a
        forced shut-down) or due to an error handling a specific
        method, i.e. an exception.  When a close is due to an
        exception, the sender provides the class and method id of the
        method which caused the exception.

        RULE:

            After sending this method any received method except the
            Close-OK method MUST be discarded.

        RULE:

            The peer sending this method MAY use a counter or timeout
            to detect failure of the other peer to respond correctly
            with the Close-OK method.

        RULE:

            When a server receives the Close method from a client it
            MUST delete all server-side resources associated with the
            client's context.  A client CANNOT reconnect to a context
            after sending or receiving a Close method.

        PARAMETERS:
            reply_code: short

                The reply code. The AMQ reply codes are defined in AMQ
                RFC 011.

            reply_text: shortstr

                The localised reply text.  This text can be logged as an
                aid to resolving issues.

            class_id: short

                failing method class

                When the close is provoked by a method exception, this
                is the class of the method.

            method_id: short

                failing method ID

                When the close is provoked by a method exception, this
                is the ID of the method.

        """
        if self.transport is None:
            # already closed
            return

        args = AMQPWriter()
        args.write_short(reply_code)
        args.write_shortstr(reply_text)
        args.write_short(method_sig[0]) # class_id
        args.write_short(method_sig[1]) # method_id
        self._send_method((10, 60), args)
        return self.wait(allowed_methods=[
                          (10, 61),    # Connection.close_ok
                        ])


    def _close(self, args):
        """
        request a connection close

        This method indicates that the sender wants to close the
        connection. This may be due to internal conditions (e.g. a
        forced shut-down) or due to an error handling a specific
        method, i.e. an exception.  When a close is due to an
        exception, the sender provides the class and method id of the
        method which caused the exception.

        RULE:

            After sending this method any received method except the
            Close-OK method MUST be discarded.

        RULE:

            The peer sending this method MAY use a counter or timeout
            to detect failure of the other peer to respond correctly
            with the Close-OK method.

        RULE:

            When a server receives the Close method from a client it
            MUST delete all server-side resources associated with the
            client's context.  A client CANNOT reconnect to a context
            after sending or receiving a Close method.

        PARAMETERS:
            reply_code: short

                The reply code. The AMQ reply codes are defined in AMQ
                RFC 011.

            reply_text: shortstr

                The localised reply text.  This text can be logged as an
                aid to resolving issues.

            class_id: short

                failing method class

                When the close is provoked by a method exception, this
                is the class of the method.

            method_id: short

                failing method ID

                When the close is provoked by a method exception, this
                is the ID of the method.

        """
        reply_code = args.read_short()
        reply_text = args.read_shortstr()
        class_id = args.read_short()
        method_id = args.read_short()

        self._x_close_ok()

        raise AMQPConnectionException(reply_code, reply_text, (class_id, method_id))


    def _x_close_ok(self):
        """
        confirm a connection close

        This method confirms a Connection.Close method and tells the
        recipient that it is safe to release resources for the
        connection and close the socket.

        RULE:

            A peer that detects a socket closure without having
            received a Close-Ok handshake method SHOULD log the error.

        """
        self._send_method((10, 61))
        self._do_close()


    def _close_ok(self, args):
        """
        confirm a connection close

        This method confirms a Connection.Close method and tells the
        recipient that it is safe to release resources for the
        connection and close the socket.

        RULE:

            A peer that detects a socket closure without having
            received a Close-Ok handshake method SHOULD log the error.

        """
        self._do_close()


    def _x_open(self, virtual_host, capabilities='', insist=False):
        """
        open connection to virtual host

        This method opens a connection to a virtual host, which is a
        collection of resources, and acts to separate multiple
        application domains within a server.

        RULE:

            The client MUST open the context before doing any work on
            the connection.

        PARAMETERS:
            virtual_host: shortstr

                virtual host name

                The name of the virtual host to work with.

                RULE:

                    If the server supports multiple virtual hosts, it
                    MUST enforce a full separation of exchanges,
                    queues, and all associated entities per virtual
                    host. An application, connected to a specific
                    virtual host, MUST NOT be able to access resources
                    of another virtual host.

                RULE:

                    The server SHOULD verify that the client has
                    permission to access the specified virtual host.

                RULE:

                    The server MAY configure arbitrary limits per
                    virtual host, such as the number of each type of
                    entity that may be used, per connection and/or in
                    total.

            capabilities: shortstr

                required capabilities

                The client may specify a number of capability names,
                delimited by spaces.  The server can use this string
                to how to process the client's connection request.

            insist: boolean

                insist on connecting to server

                In a configuration with multiple load-sharing servers,
                the server may respond to a Connection.Open method
                with a Connection.Redirect. The insist option tells
                the server that the client is insisting on a
                connection to the specified server.

                RULE:

                    When the client uses the insist option, the server
                    SHOULD accept the client connection unless it is
                    technically unable to do so.

        """
        args = AMQPWriter()
        args.write_shortstr(virtual_host)
        args.write_shortstr(capabilities)
        args.write_bit(insist)
        self._send_method((10, 40), args)
        return self.wait(allowed_methods=[
                          (10, 41),    # Connection.open_ok
                          (10, 50),    # Connection.redirect
                        ])


    def _open_ok(self, args):
        """
        signal that the connection is ready

        This method signals to the client that the connection is ready
        for use.

        PARAMETERS:
            known_hosts: shortstr

        """
        self.known_hosts = args.read_shortstr()
        AMQP_LOGGER.debug('Open OK! known_hosts [%s]' % self.known_hosts)
        return None


    def _redirect(self, args):
        """
        asks the client to use a different server

        This method redirects the client to another server, based on
        the requested virtual host and/or capabilities.

        RULE:

            When getting the Connection.Redirect method, the client
            SHOULD reconnect to the host specified, and if that host
            is not present, to any of the hosts specified in the
            known-hosts list.

        PARAMETERS:
            host: shortstr

                server to connect to

                Specifies the server to connect to.  This is an IP
                address or a DNS name, optionally followed by a colon
                and a port number. If no port number is specified, the
                client should use the default port number for the
                protocol.

            known_hosts: shortstr

        """
        host = args.read_shortstr()
        self.known_hosts = args.read_shortstr()
        AMQP_LOGGER.debug('Redirected to [%s], known_hosts [%s]' % (host, self.known_hosts))
        return host


    def _secure(self, args):
        """
        security mechanism challenge

        The SASL protocol works by exchanging challenges and responses
        until both peers have received sufficient information to
        authenticate each other.  This method challenges the client to
        provide more information.

        PARAMETERS:
            challenge: longstr

                security challenge data

                Challenge information, a block of opaque binary data
                passed to the security mechanism.

        """
        challenge = args.read_longstr()


    def _x_secure_ok(self, response):
        """
        security mechanism response

        This method attempts to authenticate, passing a block of SASL
        data for the security mechanism at the server side.

        PARAMETERS:
            response: longstr

                security response data

                A block of opaque data passed to the security
                mechanism.  The contents of this data are defined by
                the SASL security mechanism.

        """
        args = AMQPWriter()
        args.write_longstr(response)
        self._send_method((10, 21), args)


    def _start(self, args):
        """
        start connection negotiation

        This method starts the connection negotiation process by
        telling the client the protocol version that the server
        proposes, along with a list of security mechanisms which the
        client can use for authentication.

        RULE:

            If the client cannot handle the protocol version suggested
            by the server it MUST close the socket connection.

        RULE:

            The server MUST provide a protocol version that is lower
            than or equal to that requested by the client in the
            protocol header. If the server cannot support the
            specified protocol it MUST NOT send this method, but MUST
            close the socket connection.

        PARAMETERS:
            version_major: octet

                protocol major version

                The protocol major version that the server agrees to
                use, which cannot be higher than the client's major
                version.

            version_minor: octet

                protocol major version

                The protocol minor version that the server agrees to
                use, which cannot be higher than the client's minor
                version.

            server_properties: table

                server properties

            mechanisms: longstr

                available security mechanisms

                A list of the security mechanisms that the server
                supports, delimited by spaces.  Currently ASL supports
                these mechanisms: PLAIN.

            locales: longstr

                available message locales

                A list of the message locales that the server
                supports, delimited by spaces.  The locale defines the
                language in which the server will send reply texts.

                RULE:

                    All servers MUST support at least the en_US
                    locale.

        """
        self.version_major = args.read_octet()
        self.version_minor = args.read_octet()
        self.server_properties = args.read_table()
        self.mechanisms = args.read_longstr().split(' ')
        self.locales = args.read_longstr().split(' ')

        AMQP_LOGGER.debug('Start from server, version: %d.%d, properties: %s, mechanisms: %s, locales: %s'
                % (self.version_major, self.version_minor,
                   str(self.server_properties), self.mechanisms, self.locales))


    def _x_start_ok(self, client_properties, mechanism, response, locale):
        """
        select security mechanism and locale

        This method selects a SASL security mechanism. ASL uses SASL
        (RFC2222) to negotiate authentication and encryption.

        PARAMETERS:
            client_properties: table

                client properties

            mechanism: shortstr

                selected security mechanism

                A single security mechanisms selected by the client,
                which must be one of those specified by the server.

                RULE:

                    The client SHOULD authenticate using the highest-
                    level security profile it can handle from the list
                    provided by the server.

                RULE:

                    The mechanism field MUST contain one of the
                    security mechanisms proposed by the server in the
                    Start method. If it doesn't, the server MUST close
                    the socket.

            response: longstr

                security response data

                A block of opaque data passed to the security
                mechanism. The contents of this data are defined by
                the SASL security mechanism.  For the PLAIN security
                mechanism this is defined as a field table holding two
                fields, LOGIN and PASSWORD.

            locale: shortstr

                selected message locale

                A single message local selected by the client, which
                must be one of those specified by the server.

        """
        args = AMQPWriter()
        args.write_table(client_properties)
        args.write_shortstr(mechanism)
        args.write_longstr(response)
        args.write_shortstr(locale)
        self._send_method((10, 11), args)


    def _tune(self, args):
        """
        propose connection tuning parameters

        This method proposes a set of connection configuration values
        to the client.  The client can accept and/or adjust these.

        PARAMETERS:
            channel_max: short

                proposed maximum channels

                The maximum total number of channels that the server
                allows per connection. Zero means that the server does
                not impose a fixed limit, but the number of allowed
                channels may be limited by available server resources.

            frame_max: long

                proposed maximum frame size

                The largest frame size that the server proposes for
                the connection. The client can negotiate a lower
                value.  Zero means that the server does not impose any
                specific limit but may reject very large frames if it
                cannot allocate resources for them.

                RULE:

                    Until the frame-max has been negotiated, both
                    peers MUST accept frames of up to 4096 octets
                    large. The minimum non-zero value for the frame-
                    max field is 4096.

            heartbeat: short

                desired heartbeat delay

                The delay, in seconds, of the connection heartbeat
                that the server wants.  Zero means the server does not
                want a heartbeat.

        """
        self.channel_max = args.read_short() or self.channel_max
        self.frame_max = args.read_long() or self.frame_max
        self.method_writer.frame_max = self.frame_max
        self.heartbeat = args.read_short()

        self._x_tune_ok(self.channel_max, self.frame_max, 0)


    def _x_tune_ok(self, channel_max, frame_max, heartbeat):
        """
        negotiate connection tuning parameters

        This method sends the client's connection tuning parameters to
        the server. Certain fields are negotiated, others provide
        capability information.

        PARAMETERS:
            channel_max: short

                negotiated maximum channels

                The maximum total number of channels that the client
                will use per connection.  May not be higher than the
                value specified by the server.

                RULE:

                    The server MAY ignore the channel-max value or MAY
                    use it for tuning its resource allocation.

            frame_max: long

                negotiated maximum frame size

                The largest frame size that the client and server will
                use for the connection.  Zero means that the client
                does not impose any specific limit but may reject very
                large frames if it cannot allocate resources for them.
                Note that the frame-max limit applies principally to
                content frames, where large contents can be broken
                into frames of arbitrary size.

                RULE:

                    Until the frame-max has been negotiated, both
                    peers must accept frames of up to 4096 octets
                    large. The minimum non-zero value for the frame-
                    max field is 4096.

            heartbeat: short

                desired heartbeat delay

                The delay, in seconds, of the connection heartbeat
                that the client wants. Zero means the client does not
                want a heartbeat.

        """
        args = AMQPWriter()
        args.write_short(channel_max)
        args.write_long(frame_max)
        args.write_short(heartbeat)
        self._send_method((10, 31), args)
        self._wait_tune_ok = False


    _METHOD_MAP = {
        (10, 10): _start,
        (10, 20): _secure,
        (10, 30): _tune,
        (10, 41): _open_ok,
        (10, 50): _redirect,
        (10, 60): _close,
        (10, 61): _close_ok,
        }
