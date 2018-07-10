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

import datetime

import iso8601
import mock
from oslo_utils import timeutils

from nova import context
from nova.db import api as db
from nova.objects import bandwidth_usage
from nova import test
from nova.tests.unit.objects import test_objects
from nova.tests import uuidsentinel as uuids


class _TestBandwidthUsage(test.TestCase):

    def setUp(self):
        super(_TestBandwidthUsage, self).setUp()
        self.user_id = 'fake_user'
        self.project_id = 'fake_project'
        self.context = context.RequestContext(self.user_id, self.project_id)
        now, start_period = self._time_now_and_start_period()
        self.expected_bw_usage = self._fake_bw_usage(
            time=now, start_period=start_period)

    @staticmethod
    def _compare(test, db, obj, ignored_fields=None):
        if ignored_fields is None:
            ignored_fields = []
        for field, value in db.items():
            if field in ignored_fields:
                continue
            obj_field = field
            if obj_field == 'uuid':
                obj_field = 'instance_uuid'
            test.assertEqual(db[field], getattr(obj, obj_field),
                    'Field %s is not equal' % field)

    @staticmethod
    def _fake_bw_usage(time=None, start_period=None, bw_in=100,
                       bw_out=200, last_ctr_in=12345, last_ctr_out=67890):
        fake_bw_usage = {
            'created_at': None,
            'updated_at': None,
            'deleted_at': None,
            'deleted': 0,
            'uuid': uuids.instance,
            'mac': 'fake_mac1',
            'start_period': start_period,
            'bw_in': bw_in,
            'bw_out': bw_out,
            'last_ctr_in': last_ctr_in,
            'last_ctr_out': last_ctr_out,
            'last_refreshed': time
        }
        return fake_bw_usage

    @staticmethod
    def _time_now_and_start_period():
        now = timeutils.utcnow().replace(tzinfo=iso8601.UTC,
                                         microsecond=0)
        start_period = now - datetime.timedelta(seconds=10)
        return now, start_period

    @mock.patch.object(db, 'bw_usage_get')
    def test_get_by_instance_uuid_and_mac(self, mock_get):
        mock_get.return_value = self.expected_bw_usage
        bw_usage = bandwidth_usage.BandwidthUsage.get_by_instance_uuid_and_mac(
            self.context, uuids.instance, 'fake_mac',
            start_period=self.expected_bw_usage['start_period'])
        self._compare(self, self.expected_bw_usage, bw_usage)

    @mock.patch.object(db, 'bw_usage_get_by_uuids')
    def test_get_by_uuids(self, mock_get_by_uuids):
        mock_get_by_uuids.return_value = [self.expected_bw_usage]

        bw_usages = bandwidth_usage.BandwidthUsageList.get_by_uuids(
            self.context, [uuids.instance],
            start_period=self.expected_bw_usage['start_period'])
        self.assertEqual(1, len(bw_usages))
        self._compare(self, self.expected_bw_usage, bw_usages[0])

    @mock.patch.object(db, 'bw_usage_update')
    def test_create(self, mock_create):
        mock_create.return_value = self.expected_bw_usage

        bw_usage = bandwidth_usage.BandwidthUsage(context=self.context)
        bw_usage.create(uuids.instance, 'fake_mac',
                        100, 200, 12345, 67890,
                        start_period=self.expected_bw_usage['start_period'])

        self._compare(self, self.expected_bw_usage, bw_usage)

    def test_update_with_db(self):
        expected_bw_usage1 = self._fake_bw_usage(
            time=self.expected_bw_usage['last_refreshed'],
            start_period=self.expected_bw_usage['start_period'],
            last_ctr_in=42, last_ctr_out=42)

        bw_usage = bandwidth_usage.BandwidthUsage(context=self.context)
        bw_usage.create(uuids.instance, 'fake_mac1',
                        100, 200, 42, 42,
                        start_period=self.expected_bw_usage['start_period'])
        self._compare(self, expected_bw_usage1, bw_usage,
                ignored_fields=['last_refreshed', 'created_at'])
        bw_usage.create(uuids.instance, 'fake_mac1',
                        100, 200, 12345, 67890,
                        start_period=self.expected_bw_usage['start_period'])
        self._compare(self, self.expected_bw_usage, bw_usage,
                ignored_fields=['last_refreshed', 'created_at', 'updated_at'])

    @mock.patch.object(db, 'bw_usage_update')
    def test_update(self, mock_update):
        expected_bw_usage1 = self._fake_bw_usage(
            time=self.expected_bw_usage['last_refreshed'],
            start_period=self.expected_bw_usage['start_period'],
            last_ctr_in=42, last_ctr_out=42)

        mock_update.side_effect = [expected_bw_usage1, self.expected_bw_usage]

        bw_usage = bandwidth_usage.BandwidthUsage(context=self.context)
        bw_usage.create('fake_uuid1', 'fake_mac1',
                        100, 200, 42, 42,
                        start_period=self.expected_bw_usage['start_period'])
        self._compare(self, expected_bw_usage1, bw_usage)
        bw_usage.create('fake_uuid1', 'fake_mac1',
                        100, 200, 12345, 67890,
                        start_period=self.expected_bw_usage['start_period'])
        self._compare(self, self.expected_bw_usage, bw_usage)


class TestBandwidthUsageObject(test_objects._LocalTest,
                               _TestBandwidthUsage):
    pass


class TestRemoteBandwidthUsageObject(test_objects._RemoteTest,
                                     _TestBandwidthUsage):
    pass
