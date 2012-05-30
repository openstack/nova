# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright 2012 Cloudscaling Group, Inc
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

from nova import log as logging
from nova.rpc import matchmaker
from nova import test

LOG = logging.getLogger(__name__)


class _MatchMakerTestCase(test.TestCase):
    def test_valid_host_matches(self):
        queues = self.driver.queues(self.topic)
        matched_hosts = map(lambda x: x[1], queues)

        for host in matched_hosts:
            self.assertIn(host, self.hosts)

    def test_fanout_host_matches(self):
        """For known hosts, see if they're in fanout."""
        queues = self.driver.queues("fanout~" + self.topic)
        matched_hosts = map(lambda x: x[1], queues)

        LOG.info("Received result from matchmaker: %s", queues)
        for host in self.hosts:
            self.assertIn(host, matched_hosts)


class MatchMakerFileTestCase(_MatchMakerTestCase):
    def setUp(self):
        self.topic = "test"
        self.hosts = ['hello', 'world', 'foo', 'bar', 'baz']
        ring = {
            self.topic: self.hosts
        }
        self.driver = matchmaker.MatchMakerRing(ring)
        super(MatchMakerFileTestCase, self).setUp()


class MatchMakerLocalhostTestCase(_MatchMakerTestCase):
    def setUp(self):
        self.driver = matchmaker.MatchMakerLocalhost()
        self.topic = "test"
        self.hosts = ['localhost']
        super(MatchMakerLocalhostTestCase, self).setUp()
