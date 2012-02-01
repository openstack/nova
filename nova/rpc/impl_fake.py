# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright 2011 OpenStack LLC
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
"""Fake RPC implementation which calls proxy methods directly with no
queues.  Casts will block, but this is very useful for tests.
"""

import inspect
import signal
import sys
import time
import traceback

import eventlet

from nova import context
from nova import flags
from nova.rpc import common as rpc_common

CONSUMERS = {}

FLAGS = flags.FLAGS


class RpcContext(context.RequestContext):
    def __init__(self, *args, **kwargs):
        super(RpcContext, self).__init__(*args, **kwargs)
        self._response = []
        self._done = False

    def reply(self, reply=None, failure=None, ending=False):
        if ending:
            self._done = True
        if not self._done:
            self._response.append((reply, failure))


class Consumer(object):
    def __init__(self, topic, proxy):
        self.topic = topic
        self.proxy = proxy

    def call(self, context, method, args, timeout):
        node_func = getattr(self.proxy, method)
        node_args = dict((str(k), v) for k, v in args.iteritems())
        done = eventlet.event.Event()

        def _inner():
            ctxt = RpcContext.from_dict(context.to_dict())
            try:
                rval = node_func(context=ctxt, **node_args)
                res = []
                # Caller might have called ctxt.reply() manually
                for (reply, failure) in ctxt._response:
                    if failure:
                        raise failure[0], failure[1], failure[2]
                    res.append(reply)
                # if ending not 'sent'...we might have more data to
                # return from the function itself
                if not ctxt._done:
                    if inspect.isgenerator(rval):
                        for val in rval:
                            res.append(val)
                    else:
                        res.append(rval)
                done.send(res)
            except Exception:
                exc_info = sys.exc_info()
                done.send_exception(
                        rpc_common.RemoteError(exc_info[0].__name__,
                            str(exc_info[1]),
                            ''.join(traceback.format_exception(*exc_info))))

        thread = eventlet.greenthread.spawn(_inner)

        if timeout:
            start_time = time.time()
            while not done.ready():
                eventlet.greenthread.sleep(1)
                cur_time = time.time()
                if (cur_time - start_time) > timeout:
                    thread.kill()
                    raise rpc_common.Timeout()

        return done.wait()


class Connection(object):
    """Connection object."""

    def __init__(self):
        self.consumers = []

    def create_consumer(self, topic, proxy, fanout=False):
        consumer = Consumer(topic, proxy)
        self.consumers.append(consumer)
        if topic not in CONSUMERS:
            CONSUMERS[topic] = []
        CONSUMERS[topic].append(consumer)

    def close(self):
        for consumer in self.consumers:
            CONSUMERS[consumer.topic].remove(consumer)
        self.consumers = []

    def consume_in_thread(self):
        pass


def create_connection(new=True):
    """Create a connection"""
    return Connection()


def multicall(context, topic, msg, timeout=None):
    """Make a call that returns multiple times."""

    method = msg.get('method')
    if not method:
        return
    args = msg.get('args', {})

    try:
        consumer = CONSUMERS[topic][0]
    except (KeyError, IndexError):
        return iter([None])
    else:
        return consumer.call(context, method, args, timeout)


def call(context, topic, msg, timeout=None):
    """Sends a message on a topic and wait for a response."""
    rv = multicall(context, topic, msg, timeout)
    # NOTE(vish): return the last result from the multicall
    rv = list(rv)
    if not rv:
        return
    return rv[-1]


def cast(context, topic, msg):
    try:
        call(context, topic, msg)
    except rpc_common.RemoteError:
        pass


def notify(context, topic, msg):
    pass


def cleanup():
    pass


def fanout_cast(context, topic, msg):
    """Cast to all consumers of a topic"""
    method = msg.get('method')
    if not method:
        return
    args = msg.get('args', {})

    for consumer in CONSUMERS.get(topic, []):
        try:
            consumer.call(context, method, args)
        except rpc_common.RemoteError:
            pass
