# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 IBM Corp.
# Copyright 2011 OpenStack Foundation
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

import httplib

from oslo.config import cfg

from nova import test
from nova.virt.vmwareapi import read_write_util

CONF = cfg.CONF


class ReadWriteUtilTestCase(test.TestCase):
    def setUp(self):
        super(ReadWriteUtilTestCase, self).setUp()

    def test_ipv6_host(self):
        ipv6_host = 'fd8c:215d:178e:c51e:200:c9ff:fed1:584c'
        self.mox.StubOutWithMock(httplib.HTTPConnection, 'endheaders')
        httplib.HTTPConnection.endheaders()
        self.mox.ReplayAll()
        file = read_write_util.VMwareHTTPWriteFile(ipv6_host,
                                                   'fake_dc',
                                                   'fake_ds',
                                                   dict(),
                                                   '/tmp/fake.txt',
                                                   0)
        self.assertEqual(ipv6_host, file.conn.host)
        self.assertEqual(443, file.conn.port)
