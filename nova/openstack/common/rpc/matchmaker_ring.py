# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright 2011-2013 Cloudscaling Group, Inc
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

import itertools
import json

from oslo.config import cfg

from nova.openstack.common.gettextutils import _  # noqa
from nova.openstack.common import log as logging
from nova.openstack.common.rpc import matchmaker as mm


matchmaker_opts = [
    # Matchmaker ring file
    cfg.StrOpt('ringfile',
               deprecated_name='matchmaker_ringfile',
               deprecated_group='DEFAULT',
               default='/etc/oslo/matchmaker_ring.json',
               help='Matchmaker ring file (JSON)'),
]

CONF = cfg.CONF
CONF.register_opts(matchmaker_opts, 'matchmaker_ring')
LOG = logging.getLogger(__name__)


class RingExchange(mm.Exchange):
    """Match Maker where hosts are loaded from a static JSON formatted file.

    __init__ takes optional ring dictionary argument, otherwise
    loads the ringfile from CONF.mathcmaker_ringfile.
    """
    def __init__(self, ring=None):
        super(RingExchange, self).__init__()

        if ring:
            self.ring = ring
        else:
            fh = open(CONF.matchmaker_ring.ringfile, 'r')
            self.ring = json.load(fh)
            fh.close()

        self.ring0 = {}
        for k in self.ring.keys():
            self.ring0[k] = itertools.cycle(self.ring[k])

    def _ring_has(self, key):
        return key in self.ring0


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


class MatchMakerRing(mm.MatchMakerBase):
    """Match Maker where hosts are loaded from a static hashmap."""
    def __init__(self, ring=None):
        super(MatchMakerRing, self).__init__()
        self.add_binding(mm.FanoutBinding(), FanoutRingExchange(ring))
        self.add_binding(mm.DirectBinding(), mm.DirectExchange())
        self.add_binding(mm.TopicBinding(), RoundRobinRingExchange(ring))
