# Copyright (c) 2012 Intel, LLC
# Copyright (c) 2012 OpenStack, LLC
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

"""
Test multiprocess enabled EC2/OSAPI_Compute/OSAPI_Volume/Metadata API service.
"""
import boto
from boto.ec2 import regioninfo
import os
import signal
import sys
import time

from nova import flags
from nova.log import logging
from nova import service
from nova.tests.integrated import integrated_helpers

FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)


class MultiprocessEC2Test(integrated_helpers._IntegratedTestBase):
    def _start_api_service(self):
        self.osapi = service.WSGIService("ec2")
        self.osapi.start()
        self.auth_url = 'http://%s:%s/services/Cloud' % \
                        (self.osapi.host, self.osapi.port)
        LOG.warn(self.auth_url)

    def _get_flags(self):
        f = super(MultiprocessEC2Test, self)._get_flags()
        f['ec2_workers'] = 2
        return f

    def test_ec2(self):
        region = regioninfo.RegionInfo(None, 'test', self.osapi.host)
        self.ec2 = boto.connect_ec2(
                    aws_access_key_id='fake',
                    aws_secret_access_key='fake',
                    is_secure=False,
                    region=region,
                    host=self.osapi.host,
                    port=self.osapi.port,
                    path='/services/Cloud')
        result = self.ec2.get_all_regions()
        self.assertEqual(len(result), 1)


class MultiprocessMetadataTest(integrated_helpers._IntegratedTestBase):
    def _start_api_service(self):
        self.osapi = service.WSGIService("metadata")
        self.osapi.start()
        self.auth_url = 'http://%s:%s/' % (self.osapi.host, self.osapi.port)
        LOG.warn(self.auth_url)

    def _get_flags(self):
        f = super(MultiprocessMetadataTest, self)._get_flags()
        f['metadata_workers'] = 2
        return f

    def request(self, relative_url):
        return self.api.api_get(relative_url)

    def test_meta(self):
        userdata_url = self.auth_url + '/user-data'
        resp = self.api.request(userdata_url)
        self.assertEqual(resp.status, 200)


class MultiprocessOSAPIComputeTest(integrated_helpers._IntegratedTestBase):
    def _start_api_service(self):
        self.osapi = service.WSGIService("osapi_compute")
        self.osapi.start()
        self.auth_url = 'http://%s:%s/v2' % (self.osapi.host, self.osapi.port)
        LOG.warn(self.auth_url)

    def _get_flags(self):
        f = super(MultiprocessOSAPIComputeTest, self)._get_flags()
        f['osapi_compute_workers'] = 2
        return f

    def test_osapi_compute(self):
        flavors = self.api.get_flavors()
        self.assertTrue(len(flavors) > 0, 'Num of flavors > 0.')


class MultiprocessOSAPIVolumesTest(integrated_helpers._IntegratedTestBase):
    def _start_api_service(self):
        self.osapi = service.WSGIService("osapi_volume")
        self.osapi.start()
        self.auth_url = 'http://%s:%s/v1' % (self.osapi.host, self.osapi.port)
        LOG.warn(self.auth_url)

    def _get_flags(self):
        f = super(MultiprocessOSAPIVolumesTest, self)._get_flags()
        f['osapi_volume_workers'] = 2
        f['use_local_volumes'] = False  # Avoids calling local_path
        f['volume_driver'] = 'nova.volume.driver.LoggingVolumeDriver'
        return f

    def test_create_volumes(self):
        """Create Volume with API"""
        body = {'volume': {'size': 1,
                           'snapshot_id': None,
                           'display_name': None,
                           'display_description': None,
                           'volume_type': None}}
        created_volume = self.api.post_volume(body)
        self.assertTrue(created_volume['id'])


class MultiprocessWSGITest(integrated_helpers._IntegratedTestBase):
    def setUp(self):
        self.workers = 4
        super(MultiprocessWSGITest, self).setUp()

    def _start_api_service(self):
        self.osapi = service.WSGIService("osapi_compute")
        self.osapi.start()
        self.master_worker_pid = self.osapi.server.master_worker.pid
        LOG.warn('Master_work pid is: %d' % self.master_worker_pid)
        self.auth_url = 'http://%s:%s/v2' % (self.osapi.host, self.osapi.port)
        LOG.warn(self.auth_url)

    def _get_flags(self):
        f = super(MultiprocessWSGITest, self)._get_flags()
        f['osapi_compute_workers'] = self.workers
        return f

    def test_killed_worker_recover(self):
        # kill one worker and check if new worker can come up
        f = os.popen('ps --no-headers --ppid %d' % self.master_worker_pid)
        children_pid = f.readline().split()
        for pid in children_pid:
            LOG.warn('pid of first child is %s' % pid)
            if pid.isdigit():
                os.kill(int(pid), signal.SIGTERM)
                break
            else:
                continue
        # wait for new worker
        time.sleep(1.5)
        f = os.popen('ps --no-headers --ppid %d|wc -l' %
                     self.master_worker_pid)
        workers = f.readline()
        LOG.warn('# of workers: %s' % workers)
        self.assertEqual(int(workers), self.workers,
                         'Num of children = %d.' % self.workers)
        flavors = self.api.get_flavors()
        # check if api service works
        self.assertTrue(len(flavors) > 0, 'Num of flavors > 0.')

    def test_terminate_api_with_signal(self):
        # check if api service is working
        flavors = self.api.get_flavors()
        self.assertTrue(len(flavors) > 0, 'Num of flavors > 0.')
        # send SIGTERM to master_worker will terminate service
        os.kill(self.master_worker_pid, signal.SIGTERM)
        time.sleep(1.5)
        # check if service is still available (shouldn't be)
        #"""
        try:
            self.api.get_flavors()
            self.fail('API service should have been terminated')
        except Exception as ex:
            exc_value = sys.exc_info()[1]
            self.assertTrue('Connection refused' in exc_value or
                            'ECONNREFUSED' in exc_value)
        #"""
        #self.api.get_flavors()
        # check there is no OS processes left over
        f = os.popen('ps --no-headers --ppid %d' % self.master_worker_pid)
        self.assertEqual(f.readline(), '', 'No OS processes left.')
