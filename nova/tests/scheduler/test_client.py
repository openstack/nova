# Copyright (c) 2014 Red Hat, Inc.
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

import mock

from nova.conductor import api as conductor_api
from nova import context
from nova import exception
from nova.scheduler import client as scheduler_client
from nova import test
"""Tests for Scheduler Client."""


class SchedulerClientTestCase(test.TestCase):

    def setUp(self):
        super(SchedulerClientTestCase, self).setUp()
        self.context = context.get_admin_context()

        self.flags(use_local=True, group='conductor')

        self.client = scheduler_client.SchedulerClient()

    def test_constructor(self):
        self.assertIsNotNone(self.client.conductor_api)

    @mock.patch.object(conductor_api.LocalAPI, 'compute_node_update')
    def test_update_compute_node_works(self, mock_cn_update):
        stats = {"id": 1, "foo": "bar"}
        self.client.update_resource_stats(self.context,
                                          ('fakehost', 'fakenode'),
                                          stats)
        mock_cn_update.assert_called_once_with(self.context,
                                               {"id": 1},
                                               {"foo": "bar"})

    def test_update_compute_node_raises(self):
        stats = {"foo": "bar"}
        self.assertRaises(exception.ComputeHostNotCreated,
                          self.client.update_resource_stats,
                          self.context, ('fakehost', 'fakenode'), stats)
