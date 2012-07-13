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
import itertools
import json
import logging

from nova.openstack.common import cfg
from nova.openstack.common.gettextutils import _


matchmaker_opts = [
    # Matchmaker ring file
    cfg.StrOpt('matchmaker_ringfile',
               default='/etc/nova/matchmaker_ring.json',
               help='Matchmaker ring file (JSON)'),
]

CONF = cfg.CONF
CONF.register_opts(matchmaker_opts)
LOG = logging.getLogger(__name__)
contextmanager = contextlib.contextmanager


class MatchMakerException(Exception):
    """Signified a match could not be found."""
    message = _("Match not found by MatchMaker.")


class Exchange(object):
    """
    Implements lookups.
    Subclass this to support hashtables, dns, etc.
    """
    def __init__(self):
        pass

    def run(self, key):
        raise NotImplementedError()


class Binding(object):
    """
    A binding on which to perform a lookup.
    """
    def __init__(self):
        pass

    def test(self, key):
        raise NotImplementedError()


class MatchMakerBase(object):
    """Match Maker Base Class."""

    def __init__(self):
        # Array of tuples. Index [2] toggles negation, [3] is last-if-true
        self.bindings = []

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


class DirectBinding(Binding):
    """
    Specifies a host in the key via a '.' character
    Although dots are used in the key, the behavior here is
    that it maps directly to a host, thus direct.
    """
    def test(self, key):
        if '.' in key:
            return True
        return False


class TopicBinding(Binding):
    """
    Where a 'bare' key without dots.
    AMQP generally considers topic exchanges to be those *with* dots,
    but we deviate here in terminology as the behavior here matches
    that of a topic exchange (whereas where there are dots, behavior
    matches that of a direct exchange.
    """
    def test(self, key):
        if '.' not in key:
            return True
        return False


class FanoutBinding(Binding):
    """Match on fanout keys, where key starts with 'fanout.' string."""
    def test(self, key):
        if key.startswith('fanout~'):
            return True
        return False


class StubExchange(Exchange):
    """Exchange that does nothing."""
    def run(self, key):
        return [(key, None)]


class RingExchange(Exchange):
    """
    Match Maker where hosts are loaded from a static file containing
    a hashmap (JSON formatted).

    __init__ takes optional ring dictionary argument, otherwise
    loads the ringfile from CONF.mathcmaker_ringfile.
    """
    def __init__(self, ring=None):
        super(RingExchange, self).__init__()

        if ring:
            self.ring = ring
        else:
            fh = open(CONF.matchmaker_ringfile, 'r')
            self.ring = json.load(fh)
            fh.close()

        self.ring0 = {}
        for k in self.ring.keys():
            self.ring0[k] = itertools.cycle(self.ring[k])

    def _ring_has(self, key):
        if key in self.ring0:
            return True
        return False


class RoundRobinRingExchange(RingExchange):
    """A Topic Exchange based on a hashmap."""
    def __init__(self, ring=None):
        super(RoundRobinRingExchange, self).__init__(ring)

    def run(self, key):
        if not self._ring_has(key):
            LOG.warn(
                _("No key defining hosts for topic '%s', "
                  "see ringfile") % (key, )
            )
            return []
        host = next(self.ring0[key])
        return [(key + '.' + host, host)]


class FanoutRingExchange(RingExchange):
    """Fanout Exchange based on a hashmap."""
    def __init__(self, ring=None):
        super(FanoutRingExchange, self).__init__(ring)

    def run(self, key):
        # Assume starts with "fanout~", strip it for lookup.
        nkey = key.split('fanout~')[1:][0]
        if not self._ring_has(nkey):
            LOG.warn(
                _("No key defining hosts for topic '%s', "
                  "see ringfile") % (nkey, )
            )
            return []
        return map(lambda x: (key + '.' + x, x), self.ring[nkey])


class LocalhostExchange(Exchange):
    """Exchange where all direct topics are local."""
    def __init__(self):
        super(Exchange, self).__init__()

    def run(self, key):
        return [(key.split('.')[0] + '.localhost', 'localhost')]


class DirectExchange(Exchange):
    """
    Exchange where all topic keys are split, sending to second half.
    i.e. "compute.host" sends a message to "compute" running on "host"
    """
    def __init__(self):
        super(Exchange, self).__init__()

    def run(self, key):
        b, e = key.split('.', 1)
        return [(b, e)]


class MatchMakerRing(MatchMakerBase):
    """
    Match Maker where hosts are loaded from a static hashmap.
    """
    def __init__(self, ring=None):
        super(MatchMakerRing, self).__init__()
        self.add_binding(FanoutBinding(), FanoutRingExchange(ring))
        self.add_binding(DirectBinding(), DirectExchange())
        self.add_binding(TopicBinding(), RoundRobinRingExchange(ring))


class MatchMakerLocalhost(MatchMakerBase):
    """
    Match Maker where all bare topics resolve to localhost.
    Useful for testing.
    """
    def __init__(self):
        super(MatchMakerLocalhost, self).__init__()
        self.add_binding(FanoutBinding(), LocalhostExchange())
        self.add_binding(DirectBinding(), DirectExchange())
        self.add_binding(TopicBinding(), LocalhostExchange())


class MatchMakerStub(MatchMakerBase):
    """
    Match Maker where topics are untouched.
    Useful for testing, or for AMQP/brokered queues.
    Will not work where knowledge of hosts is known (i.e. zeromq)
    """
    def __init__(self):
        super(MatchMakerLocalhost, self).__init__()

        self.add_binding(FanoutBinding(), StubExchange())
        self.add_binding(DirectBinding(), StubExchange())
        self.add_binding(TopicBinding(), StubExchange())
