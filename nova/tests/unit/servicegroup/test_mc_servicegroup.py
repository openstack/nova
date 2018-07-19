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

import iso8601
import mock

from nova import servicegroup
from nova import test
from oslo_utils import timeutils


class MemcachedServiceGroupTestCase(test.NoDBTestCase):

    @mock.patch('nova.cache_utils.get_memcached_client')
    def setUp(self, mgc_mock):
        super(MemcachedServiceGroupTestCase, self).setUp()
        self.mc_client = mock.MagicMock()
        mgc_mock.return_value = self.mc_client
        self.flags(servicegroup_driver='mc')
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

    def test_get_updated_time(self):
        updated_at_time = timeutils.parse_strtime("2016-04-18T02:56:25.198871")
        service_ref = {
            'host': 'fake-host',
            'topic': 'compute',
            'updated_at': updated_at_time.replace(tzinfo=iso8601.UTC)
        }

        # If no record returned from the mc, return record from DB
        self.mc_client.get.return_value = None
        self.assertEqual(service_ref['updated_at'],
                         self.servicegroup_api.get_updated_time(service_ref))
        self.mc_client.get.assert_called_once_with('compute:fake-host')
        # If the record in mc is newer than DB, return record from mc
        self.mc_client.reset_mock()
        retval = timeutils.utcnow()
        self.mc_client.get.return_value = retval
        self.assertEqual(retval.replace(tzinfo=iso8601.UTC),
                         self.servicegroup_api.get_updated_time(service_ref))
        self.mc_client.get.assert_called_once_with('compute:fake-host')
        # If the record in DB is newer than mc, return record from DB
        self.mc_client.reset_mock()
        service_ref['updated_at'] = \
            retval.replace(tzinfo=iso8601.UTC)
        self.mc_client.get.return_value = updated_at_time
        self.assertEqual(service_ref['updated_at'],
                         self.servicegroup_api.get_updated_time(service_ref))
        self.mc_client.get.assert_called_once_with('compute:fake-host')
        # If no record returned from the DB, return the record from mc
        self.mc_client.reset_mock()
        service_ref['updated_at'] = None
        self.mc_client.get.return_value = updated_at_time
        self.assertEqual(updated_at_time.replace(tzinfo=iso8601.UTC),
                         self.servicegroup_api.get_updated_time(service_ref))
        self.mc_client.get.assert_called_once_with('compute:fake-host')
