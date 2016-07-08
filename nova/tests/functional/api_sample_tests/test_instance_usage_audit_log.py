# Copyright 2012 Nebula, Inc.
# Copyright 2013 IBM Corp.
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

from datetime import datetime

from six.moves import urllib

from nova import context
from nova import objects
from nova.tests.functional.api_sample_tests import api_sample_base


class InstanceUsageAuditLogJsonTest(api_sample_base.ApiSampleTestBaseV21):
    ADMIN_API = True
    sample_dir = "os-instance-usage-audit-log"

    def setUp(self):
        super(InstanceUsageAuditLogJsonTest, self).setUp()

        def fake_service_get_all(self, context,
                                 filters=None, set_zones=False):
            services = [objects.Service(host='samplehost0'),
                        objects.Service(host='samplehost1'),
                        objects.Service(host='samplehost2'),
                        objects.Service(host='samplehost3')]
            return services

        def fake_utcnow(with_timezone=False):
            # It is not UTC time, but no effect for testing
            return datetime(2012, 7, 3, 19, 36, 5, 0)

        self.stub_out('oslo_utils.timeutils.utcnow',
                      fake_utcnow)
        self.stub_out('nova.compute.api.HostAPI.service_get_all',
                      fake_service_get_all)

        for i in range(0, 3):
            self._create_task_log('samplehost%d' % i, i + 1)

    def _create_task_log(self, host, num_instances):
        task_log = objects.TaskLog(context.get_admin_context())
        task_log.task_name = 'instance_usage_audit'
        task_log.period_beginning = '2012-06-01 00:00:00'
        task_log.period_ending = '2012-07-01 00:00:00'
        task_log.host = host
        task_log.task_items = num_instances
        task_log.message = (
            'Instance usage audit ran for host %s, %s '
            'instances in 0.01 seconds.'
            % (host, num_instances))
        task_log.begin_task()
        task_log.errors = 1
        task_log.end_task()

    def test_show_instance_usage_audit_log(self):
        response = self._do_get('os-instance_usage_audit_log/%s' %
                                urllib.parse.quote('2012-07-05 10:00:00'))
        self._verify_response('inst-usage-audit-log-show-get-resp',
                              {}, response, 200)

    def test_index_instance_usage_audit_log(self):
        response = self._do_get('os-instance_usage_audit_log')
        self._verify_response('inst-usage-audit-log-index-get-resp',
                              {}, response, 200)
