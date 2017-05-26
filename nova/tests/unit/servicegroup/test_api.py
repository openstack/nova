# Copyright 2015 Intel Corp.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
Test the base class for the servicegroup API
"""
import mock

from nova import servicegroup
from nova import test


class ServiceGroupApiTestCase(test.NoDBTestCase):

    def setUp(self):
        super(ServiceGroupApiTestCase, self).setUp()
        self.flags(servicegroup_driver='db')
        self.servicegroup_api = servicegroup.API()
        self.driver = self.servicegroup_api._driver

    def test_join(self):
        """"""
        member = {'host': "fake-host", "topic": "compute"}
        group = "group"

        self.driver.join = mock.MagicMock(return_value=None)

        result = self.servicegroup_api.join(member, group)
        self.assertIsNone(result)
        self.driver.join.assert_called_with(member, group, None)

    def test_service_is_up(self):
        """"""
        member = {"host": "fake-host",
                  "topic": "compute",
                  "forced_down": False}

        for retval in (True, False):
            driver = self.servicegroup_api._driver
            driver.is_up = mock.MagicMock(return_value=retval)
            result = self.servicegroup_api.service_is_up(member)

            self.assertIs(result, retval)
            driver.is_up.assert_called_with(member)

        member["forced_down"] = True
        driver = self.servicegroup_api._driver
        driver.is_up = mock.MagicMock()
        result = self.servicegroup_api.service_is_up(member)
        self.assertIs(result, False)
        driver.is_up.assert_not_called()

    def test_get_updated_time(self):
        member = {"host": "fake-host",
                  "topic": "compute",
                  "forced_down": False}
        retval = "2016-11-02T22:40:31.000000"

        driver = self.servicegroup_api._driver
        driver.updated_time = mock.MagicMock(return_value=retval)
        result = self.servicegroup_api.get_updated_time(member)
        self.assertEqual(retval, result)
