# Copyright 2012 Cloudscaling, Inc.
# All Rights Reserved.
# Copyright 2013 Red Hat, Inc.
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

import datetime

from oslo_config import cfg
from oslo_utils import timeutils

from nova.api.ec2 import cloud
from nova.api.ec2 import ec2utils
from nova.compute import utils as compute_utils
from nova import context
from nova import db
from nova import exception
from nova import test
from nova.tests.unit import cast_as_call
from nova.tests.unit import fake_network
from nova.tests.unit import fake_notifier
from nova.tests.unit.image import fake

CONF = cfg.CONF
CONF.import_opt('compute_driver', 'nova.virt.driver')


class EC2ValidateTestCase(test.TestCase):
    def setUp(self):
        super(EC2ValidateTestCase, self).setUp()
        self.flags(compute_driver='nova.virt.fake.FakeDriver')

        def dumb(*args, **kwargs):
            pass

        self.stubs.Set(compute_utils, 'notify_about_instance_usage', dumb)
        fake_network.set_stub_network_methods(self.stubs)

        # set up our cloud
        self.cloud = cloud.CloudController()

        # Short-circuit the conductor service
        self.flags(use_local=True, group='conductor')

        # Stub out the notification service so we use the no-op serializer
        # and avoid lazy-load traces with the wrap_exception decorator in
        # the compute service.
        fake_notifier.stub_notifier(self.stubs)
        self.addCleanup(fake_notifier.reset)

        # set up services
        self.conductor = self.start_service('conductor',
                manager=CONF.conductor.manager)
        self.compute = self.start_service('compute')
        self.scheduter = self.start_service('scheduler')
        self.network = self.start_service('network')
        self.image_service = fake.FakeImageService()

        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id,
                                              self.project_id,
                                              is_admin=True)

        self.EC2_MALFORMED_IDS = ['foobar', '', 123]
        self.EC2_VALID__IDS = ['i-284f3a41', 'i-001', 'i-deadbeef']

        self.ec2_id_exception_map = [(x,
                exception.InvalidInstanceIDMalformed)
                for x in self.EC2_MALFORMED_IDS]
        self.ec2_id_exception_map.extend([(x, exception.InstanceNotFound)
                for x in self.EC2_VALID__IDS])
        self.volume_id_exception_map = [(x,
                exception.InvalidVolumeIDMalformed)
                for x in self.EC2_MALFORMED_IDS]
        self.volume_id_exception_map.extend([(x, exception.VolumeNotFound)
                for x in self.EC2_VALID__IDS])

        def fake_show(meh, context, id, **kwargs):
            return {'id': id,
                    'container_format': 'ami',
                    'properties': {
                        'kernel_id': 'cedef40a-ed67-4d10-800e-17455edce175',
                        'ramdisk_id': 'cedef40a-ed67-4d10-800e-17455edce175',
                        'type': 'machine',
                        'image_state': 'available'}}

        def fake_detail(self, context, **kwargs):
            image = fake_show(self, context, None)
            image['name'] = kwargs.get('name')
            return [image]

        fake.stub_out_image_service(self.stubs)
        self.stubs.Set(fake._FakeImageService, 'show', fake_show)
        self.stubs.Set(fake._FakeImageService, 'detail', fake_detail)

        self.useFixture(cast_as_call.CastAsCall(self.stubs))

        # make sure we can map ami-00000001/2 to a uuid in FakeImageService
        db.s3_image_create(self.context,
                               'cedef40a-ed67-4d10-800e-17455edce175')
        db.s3_image_create(self.context,
                               '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6')

    def tearDown(self):
        super(EC2ValidateTestCase, self).tearDown()
        fake.FakeImageService_reset()

    # EC2_API tests (InvalidInstanceID.Malformed)
    def test_console_output(self):
        for ec2_id, e in self.ec2_id_exception_map:
            self.assertRaises(e,
                              self.cloud.get_console_output,
                              context=self.context,
                              instance_id=[ec2_id])

    def test_describe_instance_attribute(self):
        for ec2_id, e in self.ec2_id_exception_map:
            self.assertRaises(e,
                              self.cloud.describe_instance_attribute,
                              context=self.context,
                              instance_id=ec2_id,
                              attribute='kernel')

    def test_instance_lifecycle(self):
        lifecycle = [self.cloud.terminate_instances,
                            self.cloud.reboot_instances,
                            self.cloud.stop_instances,
                            self.cloud.start_instances,
                    ]
        for cmd in lifecycle:
            for ec2_id, e in self.ec2_id_exception_map:
                self.assertRaises(e,
                                  cmd,
                                  context=self.context,
                                  instance_id=[ec2_id])

    def test_create_image(self):
        for ec2_id, e in self.ec2_id_exception_map:
            self.assertRaises(e,
                              self.cloud.create_image,
                              context=self.context,
                              instance_id=ec2_id)

    def test_create_snapshot(self):
        for ec2_id, e in self.volume_id_exception_map:
            self.assertRaises(e,
                              self.cloud.create_snapshot,
                              context=self.context,
                              volume_id=ec2_id)

    def test_describe_volumes(self):
        for ec2_id, e in self.volume_id_exception_map:
            self.assertRaises(e,
                              self.cloud.describe_volumes,
                              context=self.context,
                              volume_id=[ec2_id])

    def test_delete_volume(self):
        for ec2_id, e in self.volume_id_exception_map:
            self.assertRaises(e,
                              self.cloud.delete_volume,
                              context=self.context,
                              volume_id=ec2_id)

    def test_detach_volume(self):
        for ec2_id, e in self.volume_id_exception_map:
            self.assertRaises(e,
                              self.cloud.detach_volume,
                              context=self.context,
                              volume_id=ec2_id)


class EC2TimestampValidationTestCase(test.NoDBTestCase):
    """Test case for EC2 request timestamp validation."""

    def test_validate_ec2_timestamp_valid(self):
        params = {'Timestamp': '2011-04-22T11:29:49Z'}
        expired = ec2utils.is_ec2_timestamp_expired(params)
        self.assertFalse(expired)

    def test_validate_ec2_timestamp_old_format(self):
        params = {'Timestamp': '2011-04-22T11:29:49'}
        expired = ec2utils.is_ec2_timestamp_expired(params)
        self.assertTrue(expired)

    def test_validate_ec2_timestamp_not_set(self):
        params = {}
        expired = ec2utils.is_ec2_timestamp_expired(params)
        self.assertFalse(expired)

    def test_validate_ec2_timestamp_ms_time_regex(self):
        result = ec2utils._ms_time_regex.match('2011-04-22T11:29:49.123Z')
        self.assertIsNotNone(result)
        result = ec2utils._ms_time_regex.match('2011-04-22T11:29:49.123456Z')
        self.assertIsNotNone(result)
        result = ec2utils._ms_time_regex.match('2011-04-22T11:29:49.1234567Z')
        self.assertIsNone(result)
        result = ec2utils._ms_time_regex.match('2011-04-22T11:29:49.123')
        self.assertIsNone(result)
        result = ec2utils._ms_time_regex.match('2011-04-22T11:29:49Z')
        self.assertIsNone(result)

    def test_validate_ec2_timestamp_aws_sdk_format(self):
        params = {'Timestamp': '2011-04-22T11:29:49.123Z'}
        expired = ec2utils.is_ec2_timestamp_expired(params)
        self.assertFalse(expired)
        expired = ec2utils.is_ec2_timestamp_expired(params, expires=300)
        self.assertTrue(expired)

    def test_validate_ec2_timestamp_invalid_format(self):
        params = {'Timestamp': '2011-04-22T11:29:49.000P'}
        expired = ec2utils.is_ec2_timestamp_expired(params)
        self.assertTrue(expired)

    def test_validate_ec2_timestamp_advanced_time(self):

        # EC2 request with Timestamp in advanced time
        timestamp = timeutils.utcnow() + datetime.timedelta(seconds=250)
        params = {'Timestamp': timeutils.strtime(timestamp,
                                           "%Y-%m-%dT%H:%M:%SZ")}
        expired = ec2utils.is_ec2_timestamp_expired(params, expires=300)
        self.assertFalse(expired)

    def test_validate_ec2_timestamp_advanced_time_expired(self):
        timestamp = timeutils.utcnow() + datetime.timedelta(seconds=350)
        params = {'Timestamp': timeutils.strtime(timestamp,
                                           "%Y-%m-%dT%H:%M:%SZ")}
        expired = ec2utils.is_ec2_timestamp_expired(params, expires=300)
        self.assertTrue(expired)

    def test_validate_ec2_req_timestamp_not_expired(self):
        params = {'Timestamp': timeutils.isotime()}
        expired = ec2utils.is_ec2_timestamp_expired(params, expires=15)
        self.assertFalse(expired)

    def test_validate_ec2_req_timestamp_expired(self):
        params = {'Timestamp': '2011-04-22T12:00:00Z'}
        compare = ec2utils.is_ec2_timestamp_expired(params, expires=300)
        self.assertTrue(compare)

    def test_validate_ec2_req_expired(self):
        params = {'Expires': timeutils.isotime()}
        expired = ec2utils.is_ec2_timestamp_expired(params)
        self.assertTrue(expired)

    def test_validate_ec2_req_not_expired(self):
        expire = timeutils.utcnow() + datetime.timedelta(seconds=350)
        params = {'Expires': timeutils.strtime(expire, "%Y-%m-%dT%H:%M:%SZ")}
        expired = ec2utils.is_ec2_timestamp_expired(params)
        self.assertFalse(expired)

    def test_validate_Expires_timestamp_invalid_format(self):

        # EC2 request with invalid Expires
        params = {'Expires': '2011-04-22T11:29:49'}
        expired = ec2utils.is_ec2_timestamp_expired(params)
        self.assertTrue(expired)

    def test_validate_ec2_req_timestamp_Expires(self):

        # EC2 request with both Timestamp and Expires
        params = {'Timestamp': '2011-04-22T11:29:49Z',
                  'Expires': timeutils.isotime()}
        self.assertRaises(exception.InvalidRequest,
                          ec2utils.is_ec2_timestamp_expired,
                          params)
