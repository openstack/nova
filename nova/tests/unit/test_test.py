# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Tests for the testing base code."""

from oslo_config import cfg
import oslo_messaging as messaging

from nova.openstack.common import log as logging
from nova import rpc
from nova import test
from nova.tests import fixtures

LOG = logging.getLogger(__name__)

CONF = cfg.CONF
CONF.import_opt('use_local', 'nova.conductor.api', group='conductor')


class IsolationTestCase(test.TestCase):
    """Ensure that things are cleaned up after failed tests.

    These tests don't really do much here, but if isolation fails a bunch
    of other tests should fail.

    """
    def test_service_isolation(self):
        self.flags(use_local=True, group='conductor')
        self.useFixture(fixtures.ServiceFixture('compute'))

    def test_rpc_consumer_isolation(self):
        class NeverCalled(object):

            def __getattribute__(*args):
                assert False, "I should never get called."

        server = rpc.get_server(messaging.Target(topic='compute',
                                                 server=CONF.host),
                                endpoints=[NeverCalled()])
        server.start()


class BadLogTestCase(test.TestCase):
    """Make sure a mis-formatted debug log will get caught."""

    def test_bad_debug_log(self):
        self.assertRaises(KeyError,
            LOG.debug, "this is a misformated %(log)s", {'nothing': 'nothing'})
