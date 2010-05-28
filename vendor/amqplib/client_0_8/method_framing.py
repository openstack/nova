"""
Convert between frames and higher-level AMQP methods

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

from Queue import Empty, Queue
from struct import pack, unpack

try:
    from collections import defaultdict
except:
    class defaultdict(dict):
        """
        Mini-implementation of collections.defaultdict that
        appears in Python 2.5 and up.

        """
        def __init__(self, default_factory):
            dict.__init__(self)
            self.default_factory = default_factory

        def __getitem__(self, key):
            try:
                return dict.__getitem__(self, key)
            except KeyError:
                result = self.default_factory()
                dict.__setitem__(self, key, result)
                return result


from basic_message import Message
from exceptions import *
from serialization import AMQPReader

__all__ =  [
            'MethodReader',
           ]

#
# MethodReader needs to know which methods are supposed
# to be followed by content headers and bodies.
#
_CONTENT_METHODS = [
    (60, 50), # Basic.return
    (60, 60), # Basic.deliver
    (60, 71), # Basic.get_ok
    ]


class _PartialMessage(object):
    """
    Helper class to build up a multi-frame method.

    """
    def __init__(self, method_sig, args):
        self.method_sig = method_sig
        self.args = args
        self.msg = Message()
        self.body_parts = []
        self.body_received = 0
        self.body_size = None
        self.complete = False


    def add_header(self, payload):
        class_id, weight, self.body_size = unpack('>HHQ', payload[:12])
        self.msg._load_properties(payload[12:])
        self.complete = (self.body_size == 0)


    def add_payload(self, payload):
        self.body_parts.append(payload)
        self.body_received += len(payload)

        if self.body_received == self.body_size:
            self.msg.body = ''.join(self.body_parts)
            self.complete = True


class MethodReader(object):
    """
    Helper class to receive frames from the broker, combine them if
    necessary with content-headers and content-bodies into complete methods.

    Normally a method is represented as a tuple containing
    (channel, method_sig, args, content).

    In the case of a framing error, an AMQPConnectionException is placed
    in the queue.

    In the case of unexpected frames, a tuple made up of
    (channel, AMQPChannelException) is placed in the queue.

    """
    def __init__(self, source):
        self.source = source
        self.queue = Queue()
        self.running = False
        self.partial_messages = {}
        # For each channel, which type is expected next
        self.expected_types = defaultdict(lambda:1)


    def _next_method(self):
        """
        Read the next method from the source, once one complete method has
        been assembled it is placed in the internal queue.

        """
        while self.queue.empty():
            try:
                frame_type, channel, payload = self.source.read_frame()
            except Exception, e:
                #
                # Connection was closed?  Framing Error?
                #
                self.queue.put(e)
                break

            if self.expected_types[channel] != frame_type:
                self.queue.put((
                    channel,
                    Exception('Received frame type %s while expecting type: %s' %
                        (frame_type, self.expected_types[channel])
                        )
                    ))
            elif frame_type == 1:
                self._process_method_frame(channel, payload)
            elif frame_type == 2:
                self._process_content_header(channel, payload)
            elif frame_type == 3:
                self._process_content_body(channel, payload)


    def _process_method_frame(self, channel, payload):
        """
        Process Method frames

        """
        method_sig = unpack('>HH', payload[:4])
        args = AMQPReader(payload[4:])

        if method_sig in _CONTENT_METHODS:
            #
            # Save what we've got so far and wait for the content-header
            #
            self.partial_messages[channel] = _PartialMessage(method_sig, args)
            self.expected_types[channel] = 2
        else:
            self.queue.put((channel, method_sig, args, None))


    def _process_content_header(self, channel, payload):
        """
        Process Content Header frames

        """
        partial = self.partial_messages[channel]
        partial.add_header(payload)

        if partial.complete:
            #
            # a bodyless message, we're done
            #
            self.queue.put((channel, partial.method_sig, partial.args, partial.msg))
            del self.partial_messages[channel]
            self.expected_types[channel] = 1
        else:
            #
            # wait for the content-body
            #
            self.expected_types[channel] = 3


    def _process_content_body(self, channel, payload):
        """
        Process Content Body frames

        """
        partial = self.partial_messages[channel]
        partial.add_payload(payload)
        if partial.complete:
            #
            # Stick the message in the queue and go back to
            # waiting for method frames
            #
            self.queue.put((channel, partial.method_sig, partial.args, partial.msg))
            del self.partial_messages[channel]
            self.expected_types[channel] = 1


    def read_method(self):
        """
        Read a method from the peer.

        """
        self._next_method()
        m = self.queue.get()
        if isinstance(m, Exception):
            raise m
        return m


class MethodWriter(object):
    """
    Convert AMQP methods into AMQP frames and send them out
    to the peer.

    """
    def __init__(self, dest, frame_max):
        self.dest = dest
        self.frame_max = frame_max


    def write_method(self, channel, method_sig, args, content=None):
        payload = pack('>HH', method_sig[0], method_sig[1]) + args

        self.dest.write_frame(1, channel, payload)

        if content:
            body = content.body
            payload = pack('>HHQ', method_sig[0], 0, len(body)) + \
                content._serialize_properties()

            self.dest.write_frame(2, channel, payload)

            while body:
                payload, body = body[:self.frame_max - 8], body[self.frame_max -8:]
                self.dest.write_frame(3, channel, payload)
