# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Cloudscaling, Inc.
# Author: Joe Gordon <jogo@cloudscaling.com>
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

from nova.api.ec2 import cloud
from nova.compute import utils as compute_utils
from nova import context
from nova import db
from nova import exception
from nova import flags
from nova.openstack.common import log as logging
from nova.openstack.common import rpc
from nova import test
from nova.tests import fake_network
from nova.tests.image import fake

LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS


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

        # set up services
        self.compute = self.start_service('compute')
        self.scheduter = self.start_service('scheduler')
        self.network = self.start_service('network')
        self.volume = self.start_service('volume')
        self.image_service = fake.FakeImageService()

        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id,
                                              self.project_id,
                                              is_admin=True)

        self.EC2_MALFORMED_IDS = ['foobar', '', 123]
        self.EC2_VALID__IDS = ['i-284f3a41', 'i-001', 'i-deadbeef']

        self.ec2_id_exception_map = [(x, exception.InvalidInstanceIDMalformed)
                for x in self.EC2_MALFORMED_IDS]
        self.ec2_id_exception_map.extend([(x, exception.InstanceNotFound)
                for x in self.EC2_VALID__IDS])
        self.volume_id_exception_map = [(x,
                exception.InvalidInstanceIDMalformed)
                for x in self.EC2_MALFORMED_IDS]
        self.volume_id_exception_map.extend([(x, exception.VolumeNotFound)
                for x in self.EC2_VALID__IDS])

        def fake_show(meh, context, id):
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

        # NOTE(comstud): Make 'cast' behave like a 'call' which will
        # ensure that operations complete
        self.stubs.Set(rpc, 'cast', rpc.call)

        # make sure we can map ami-00000001/2 to a uuid in FakeImageService
        db.api.s3_image_create(self.context,
                               'cedef40a-ed67-4d10-800e-17455edce175')
        db.api.s3_image_create(self.context,
                               '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6')

    def tearDown(self):
        super(EC2ValidateTestCase, self).tearDown()
        fake.FakeImageService_reset()

    #EC2_API tests (InvalidInstanceID.Malformed)
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
