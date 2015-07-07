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
import oslo_messaging as messaging

from nova import context
from nova import objects
from nova.objects import pci_device_pool
from nova.scheduler import client as scheduler_client
from nova.scheduler.client import query as scheduler_query_client
from nova.scheduler.client import report as scheduler_report_client
from nova.scheduler import rpcapi as scheduler_rpcapi
from nova import test
"""Tests for Scheduler Client."""


class SchedulerReportClientTestCase(test.NoDBTestCase):

    def setUp(self):
        super(SchedulerReportClientTestCase, self).setUp()
        self.context = context.get_admin_context()

        self.flags(use_local=True, group='conductor')

        self.client = scheduler_report_client.SchedulerReportClient()

    @mock.patch.object(objects.ComputeNode, 'save')
    def test_update_resource_stats_saves(self, mock_save):
        cn = objects.ComputeNode()
        cn.host = 'fakehost'
        cn.hypervisor_hostname = 'fakenode'
        cn.pci_device_pools = pci_device_pool.from_pci_stats(
            [{"vendor_id": "foo",
              "product_id": "foo",
              "count": 1,
              "a": "b"}])
        self.client.update_resource_stats(cn)
        mock_save.assert_called_once_with()


class SchedulerQueryClientTestCase(test.NoDBTestCase):

    def setUp(self):
        super(SchedulerQueryClientTestCase, self).setUp()
        self.context = context.get_admin_context()

        self.client = scheduler_query_client.SchedulerQueryClient()

    def test_constructor(self):
        self.assertIsNotNone(self.client.scheduler_rpcapi)

    @mock.patch.object(scheduler_rpcapi.SchedulerAPI, 'select_destinations')
    def test_select_destinations(self, mock_select_destinations):
        fake_spec = objects.RequestSpec()
        self.client.select_destinations(
            context=self.context,
            spec_obj=fake_spec
        )
        mock_select_destinations.assert_called_once_with(
            self.context, fake_spec)

    @mock.patch.object(scheduler_rpcapi.SchedulerAPI, 'update_aggregates')
    def test_update_aggregates(self, mock_update_aggs):
        aggregates = [objects.Aggregate(id=1)]
        self.client.update_aggregates(
            context=self.context,
            aggregates=aggregates)
        mock_update_aggs.assert_called_once_with(
            self.context, aggregates)

    @mock.patch.object(scheduler_rpcapi.SchedulerAPI, 'delete_aggregate')
    def test_delete_aggregate(self, mock_delete_agg):
        aggregate = objects.Aggregate(id=1)
        self.client.delete_aggregate(
            context=self.context,
            aggregate=aggregate)
        mock_delete_agg.assert_called_once_with(
            self.context, aggregate)


class SchedulerClientTestCase(test.NoDBTestCase):

    def setUp(self):
        super(SchedulerClientTestCase, self).setUp()
        self.client = scheduler_client.SchedulerClient()

    def test_constructor(self):
        self.assertIsNotNone(self.client.queryclient)
        self.assertIsNotNone(self.client.reportclient)

    @mock.patch.object(scheduler_query_client.SchedulerQueryClient,
                       'select_destinations')
    def test_select_destinations(self, mock_select_destinations):
        fake_spec = objects.RequestSpec()
        self.assertIsNone(self.client.queryclient.instance)

        self.client.select_destinations('ctxt', fake_spec)

        self.assertIsNotNone(self.client.queryclient.instance)
        mock_select_destinations.assert_called_once_with('ctxt', fake_spec)

    @mock.patch.object(scheduler_query_client.SchedulerQueryClient,
                       'select_destinations',
                       side_effect=messaging.MessagingTimeout())
    def test_select_destinations_timeout(self, mock_select_destinations):
        # check if the scheduler service times out properly
        fake_spec = objects.RequestSpec()
        fake_args = ['ctxt', fake_spec]
        self.assertRaises(messaging.MessagingTimeout,
                          self.client.select_destinations, *fake_args)
        mock_select_destinations.assert_has_calls([mock.call(*fake_args)] * 2)

    @mock.patch.object(scheduler_query_client.SchedulerQueryClient,
                       'select_destinations', side_effect=[
                           messaging.MessagingTimeout(), mock.DEFAULT])
    def test_select_destinations_timeout_once(self, mock_select_destinations):
        # scenario: the scheduler service times out & recovers after failure
        fake_spec = objects.RequestSpec()
        fake_args = ['ctxt', fake_spec]
        self.client.select_destinations(*fake_args)
        mock_select_destinations.assert_has_calls([mock.call(*fake_args)] * 2)

    @mock.patch.object(scheduler_query_client.SchedulerQueryClient,
                       'update_aggregates')
    def test_update_aggregates(self, mock_update_aggs):
        aggregates = [objects.Aggregate(id=1)]
        self.client.update_aggregates(
            context='context',
            aggregates=aggregates)
        mock_update_aggs.assert_called_once_with(
            'context', aggregates)

    @mock.patch.object(scheduler_query_client.SchedulerQueryClient,
                       'delete_aggregate')
    def test_delete_aggregate(self, mock_delete_agg):
        aggregate = objects.Aggregate(id=1)
        self.client.delete_aggregate(
            context='context',
            aggregate=aggregate)
        mock_delete_agg.assert_called_once_with(
            'context', aggregate)

    @mock.patch.object(scheduler_report_client.SchedulerReportClient,
                       'update_resource_stats')
    def test_update_resource_stats(self, mock_update_resource_stats):
        self.assertIsNone(self.client.reportclient.instance)

        self.client.update_resource_stats(mock.sentinel.cn)

        self.assertIsNotNone(self.client.reportclient.instance)
        mock_update_resource_stats.assert_called_once_with(mock.sentinel.cn)
