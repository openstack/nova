# Copyright (c) 2013 Akira Yoshiyama <akirayoshiyama at gmail dot com>
#
# This is derived from test_db_servicegroup.py.
# Copyright 2012 IBM Corp.
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

import mock

from nova import servicegroup
from nova import test


class MemcachedServiceGroupTestCase(test.NoDBTestCase):

    @mock.patch('nova.cache_utils.get_memcached_client')
    def setUp(self, mgc_mock):
        super(MemcachedServiceGroupTestCase, self).setUp()
        self.mc_client = mock.MagicMock()
        mgc_mock.return_value = self.mc_client
        self.flags(memcached_servers='ignored',
                   servicegroup_driver='mc')
        self.servicegroup_api = servicegroup.API()

    def test_is_up(self):
        service_ref = {
            'host': 'fake-host',
            'topic': 'compute'
        }
        self.mc_client.get.return_value = None

        self.assertFalse(self.servicegroup_api.service_is_up(service_ref))
        self.mc_client.get.assert_called_once_with('compute:fake-host')
        self.mc_client.reset_mock()
        self.mc_client.get.return_value = True
        self.assertTrue(self.servicegroup_api.service_is_up(service_ref))
        self.mc_client.get.assert_called_once_with('compute:fake-host')

    def test_join(self):
        service = mock.MagicMock(report_interval=1)

        self.servicegroup_api.join('fake-host', 'fake-topic', service)
        fn = self.servicegroup_api._driver._report_state
        service.tg.add_timer.assert_called_once_with(1, fn, 5, service)

    def test_report_state(self):
        service_ref = {
            'host': 'fake-host',
            'topic': 'compute'
        }
        service = mock.MagicMock(model_disconnected=False,
                                 service_ref=service_ref)
        fn = self.servicegroup_api._driver._report_state
        fn(service)
        self.mc_client.set.assert_called_once_with('compute:fake-host',
                                                   mock.ANY)
