# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright 2011 Cloudscaling Group, Inc
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
The MatchMaker classes should except a Topic or Fanout exchange key and
return keys for direct exchanges, per (approximate) AMQP parlance.
"""

import contextlib

import eventlet
from oslo.config import cfg

from nova.openstack.common.gettextutils import _  # noqa
from nova.openstack.common import log as logging


matchmaker_opts = [
    cfg.IntOpt('matchmaker_heartbeat_freq',
               default=300,
               help='Heartbeat frequency'),
    cfg.IntOpt('matchmaker_heartbeat_ttl',
               default=600,
               help='Heartbeat time-to-live.'),
]

CONF = cfg.CONF
CONF.register_opts(matchmaker_opts)
LOG = logging.getLogger(__name__)
contextmanager = contextlib.contextmanager


class MatchMakerException(Exception):
    """Signified a match could not be found."""
    message = _("Match not found by MatchMaker.")


class Exchange(object):
    """Implements lookups.

    Subclass this to support hashtables, dns, etc.
    """
    def __init__(self):
        pass

    def run(self, key):
        raise NotImplementedError()


class Binding(object):
    """A binding on which to perform a lookup."""
    def __init__(self):
        pass

    def test(self, key):
        raise NotImplementedError()


class MatchMakerBase(object):
    """Match Maker Base Class.

    Build off HeartbeatMatchMakerBase if building a heartbeat-capable
    MatchMaker.
    """
    def __init__(self):
        # Array of tuples. Index [2] toggles negation, [3] is last-if-true
        self.bindings = []

        self.no_heartbeat_msg = _('Matchmaker does not implement '
                                  'registration or heartbeat.')

    def register(self, key, host):
        """Register a host on a backend.

        Heartbeats, if applicable, may keepalive registration.
        """
        pass

    def ack_alive(self, key, host):
        """Acknowledge that a key.host is alive.

        Used internally for updating heartbeats, but may also be used
        publically to acknowledge a system is alive (i.e. rpc message
        successfully sent to host)
        """
        pass

    def is_alive(self, topic, host):
        """Checks if a host is alive."""
        pass

    def expire(self, topic, host):
        """Explicitly expire a host's registration."""
        pass

    def send_heartbeats(self):
        """Send all heartbeats.

        Use start_heartbeat to spawn a heartbeat greenthread,
        which loops this method.
        """
        pass

    def unregister(self, key, host):
        """Unregister a topic."""
        pass

    def start_heartbeat(self):
        """Spawn heartbeat greenthread."""
        pass

    def stop_heartbeat(self):
        """Destroys the heartbeat greenthread."""
        pass

    def add_binding(self, binding, rule, last=True):
        self.bindings.append((binding, rule, False, last))

    #NOTE(ewindisch): kept the following method in case we implement the
    #                 underlying support.
    #def add_negate_binding(self, binding, rule, last=True):
    #    self.bindings.append((binding, rule, True, last))

    def queues(self, key):
        workers = []

        # bit is for negate bindings - if we choose to implement it.
        # last stops processing rules if this matches.
        for (binding, exchange, bit, last) in self.bindings:
            if binding.test(key):
                workers.extend(exchange.run(key))

                # Support last.
                if last:
                    return workers
        return workers


class HeartbeatMatchMakerBase(MatchMakerBase):
    """Base for a heart-beat capable MatchMaker.

    Provides common methods for registering, unregistering, and maintaining
    heartbeats.
    """
    def __init__(self):
        self.hosts = set()
        self._heart = None
        self.host_topic = {}

        super(HeartbeatMatchMakerBase, self).__init__()

    def send_heartbeats(self):
        """Send all heartbeats.

        Use start_heartbeat to spawn a heartbeat greenthread,
        which loops this method.
        """
        for key, host in self.host_topic:
            self.ack_alive(key, host)

    def ack_alive(self, key, host):
        """Acknowledge that a host.topic is alive.

        Used internally for updating heartbeats, but may also be used
        publically to acknowledge a system is alive (i.e. rpc message
        successfully sent to host)
        """
        raise NotImplementedError("Must implement ack_alive")

    def backend_register(self, key, host):
        """Implements registration logic.

        Called by register(self,key,host)
        """
        raise NotImplementedError("Must implement backend_register")

    def backend_unregister(self, key, key_host):
        """Implements de-registration logic.

        Called by unregister(self,key,host)
        """
        raise NotImplementedError("Must implement backend_unregister")

    def register(self, key, host):
        """Register a host on a backend.

        Heartbeats, if applicable, may keepalive registration.
        """
        self.hosts.add(host)
        self.host_topic[(key, host)] = host
        key_host = '.'.join((key, host))

        self.backend_register(key, key_host)

        self.ack_alive(key, host)

    def unregister(self, key, host):
        """Unregister a topic."""
        if (key, host) in self.host_topic:
            del self.host_topic[(key, host)]

        self.hosts.discard(host)
        self.backend_unregister(key, '.'.join((key, host)))

        LOG.info(_("Matchmaker unregistered: %(key)s, %(host)s"),
                 {'key': key, 'host': host})

    def start_heartbeat(self):
        """Implementation of MatchMakerBase.start_heartbeat.

        Launches greenthread looping send_heartbeats(),
        yielding for CONF.matchmaker_heartbeat_freq seconds
        between iterations.
        """
        if not self.hosts:
            raise MatchMakerException(
                _("Register before starting heartbeat."))

        def do_heartbeat():
            while True:
                self.send_heartbeats()
                eventlet.sleep(CONF.matchmaker_heartbeat_freq)

        self._heart = eventlet.spawn(do_heartbeat)

    def stop_heartbeat(self):
        """Destroys the heartbeat greenthread."""
        if self._heart:
            self._heart.kill()


class DirectBinding(Binding):
    """Specifies a host in the key via a '.' character.

    Although dots are used in the key, the behavior here is
    that it maps directly to a host, thus direct.
    """
    def test(self, key):
        return '.' in key


class TopicBinding(Binding):
    """Where a 'bare' key without dots.

    AMQP generally considers topic exchanges to be those *with* dots,
    but we deviate here in terminology as the behavior here matches
    that of a topic exchange (whereas where there are dots, behavior
    matches that of a direct exchange.
    """
    def test(self, key):
        return '.' not in key


class FanoutBinding(Binding):
    """Match on fanout keys, where key starts with 'fanout.' string."""
    def test(self, key):
        return key.startswith('fanout~')


class StubExchange(Exchange):
    """Exchange that does nothing."""
    def run(self, key):
        return [(key, None)]


class LocalhostExchange(Exchange):
    """Exchange where all direct topics are local."""
    def __init__(self, host='localhost'):
        self.host = host
        super(Exchange, self).__init__()

    def run(self, key):
        return [('.'.join((key.split('.')[0], self.host)), self.host)]


class DirectExchange(Exchange):
    """Exchange where all topic keys are split, sending to second half.

    i.e. "compute.host" sends a message to "compute.host" running on "host"
    """
    def __init__(self):
        super(Exchange, self).__init__()

    def run(self, key):
        e = key.split('.', 1)[1]
        return [(key, e)]


class MatchMakerLocalhost(MatchMakerBase):
    """Match Maker where all bare topics resolve to localhost.

    Useful for testing.
    """
    def __init__(self, host='localhost'):
        super(MatchMakerLocalhost, self).__init__()
        self.add_binding(FanoutBinding(), LocalhostExchange(host))
        self.add_binding(DirectBinding(), DirectExchange())
        self.add_binding(TopicBinding(), LocalhostExchange(host))


class MatchMakerStub(MatchMakerBase):
    """Match Maker where topics are untouched.

    Useful for testing, or for AMQP/brokered queues.
    Will not work where knowledge of hosts is known (i.e. zeromq)
    """
    def __init__(self):
        super(MatchMakerStub, self).__init__()

        self.add_binding(FanoutBinding(), StubExchange())
        self.add_binding(DirectBinding(), StubExchange())
        self.add_binding(TopicBinding(), StubExchange())
