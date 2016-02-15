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

import urllib

import mock

from nova import test
from nova.virt.vmwareapi import read_write_util


class ReadWriteUtilTestCase(test.NoDBTestCase):

    def test_ipv6_host_read(self):
        ipv6_host = 'fd8c:215d:178e:c51e:200:c9ff:fed1:584c'
        port = 7443
        folder = 'tmp/fake.txt'
        # NOTE(sdague): the VMwareHTTPReadFile makes implicit http
        # call via requests during construction, block that from
        # happening here in the test.
        with mock.patch.object(read_write_util.VMwareHTTPReadFile,
                               '_create_read_connection'):
            reader = read_write_util.VMwareHTTPReadFile(ipv6_host,
                                                        port,
                                                        'fake_dc',
                                                        'fake_ds',
                                                        dict(),
                                                        folder)
            param_list = {"dcPath": 'fake_dc', "dsName": 'fake_ds'}
            base_url = 'https://[%s]:%s/folder/%s' % (ipv6_host, port, folder)
            base_url += '?' + urllib.urlencode(param_list)
            self.assertEqual(base_url, reader._base_url)
