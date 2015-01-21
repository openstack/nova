#  Copyright 2012 Cloudbase Solutions Srl
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
Test suite for the Hyper-V driver and related APIs.
"""

import time
import uuid

from mox3 import mox
from oslo_config import cfg
from oslo_utils import fileutils

from nova.api.metadata import base as instance_metadata
from nova import context
from nova.image import glance
from nova import objects
from nova import test
from nova.tests.unit import fake_instance
from nova.tests.unit import fake_network
from nova.tests.unit.image import fake as fake_image
from nova.tests.unit.virt.hyperv import db_fakes
from nova.tests.unit.virt.hyperv import fake
from nova import utils
from nova.virt import configdrive
from nova.virt.hyperv import driver as driver_hyperv
from nova.virt.hyperv import hostutils
from nova.virt.hyperv import ioutils
from nova.virt.hyperv import pathutils
from nova.virt.hyperv import rdpconsoleutils
from nova.virt.hyperv import vmutils
from nova.virt import images

CONF = cfg.CONF
CONF.import_opt('vswitch_name', 'nova.virt.hyperv.vif', 'hyperv')


class HyperVAPIBaseTestCase(test.NoDBTestCase):
    """Base unit tests class for Hyper-V driver calls."""

    def __init__(self, test_case_name):
        self._mox = mox.Mox()
        super(HyperVAPIBaseTestCase, self).__init__(test_case_name)

    def setUp(self):
        super(HyperVAPIBaseTestCase, self).setUp()

        self._user_id = 'fake'
        self._project_id = 'fake'
        self._instance = None
        self._image_metadata = None
        self._fetched_image = None
        self._update_image_raise_exception = False
        self._volume_target_portal = 'testtargetportal:3260'
        self._volume_id = '0ef5d708-45ab-4129-8c59-d774d2837eb7'
        self._context = context.RequestContext(self._user_id, self._project_id)
        self._instance_disks = []
        self._instance_dvds = []
        self._instance_volume_disks = []
        self._test_vm_name = None
        self._test_instance_dir = 'C:\\FakeInstancesPath\\instance-0000001'
        self._check_min_windows_version_satisfied = True

        self._setup_stubs()

        self.flags(instances_path=r'C:\Hyper-V\test\instances',
                   network_api_class='nova.network.neutronv2.api.API')
        self.flags(force_volumeutils_v1=True, group='hyperv')
        self.flags(force_hyperv_utils_v1=True, group='hyperv')

        self._conn = driver_hyperv.HyperVDriver(None)

    def _setup_stubs(self):
        db_fakes.stub_out_db_instance_api(self.stubs)
        fake_image.stub_out_image_service(self.stubs)
        fake_network.stub_out_nw_api_get_instance_nw_info(self.stubs)

        def fake_fetch(context, image_id, target, user, project):
            self._fetched_image = target
        self.stubs.Set(images, 'fetch', fake_fetch)

        def fake_get_remote_image_service(context, name):
            class FakeGlanceImageService(object):
                def update(self_fake, context, image_id, image_metadata, f):
                    if self._update_image_raise_exception:
                        raise vmutils.HyperVException(
                            "Simulated update failure")
                    self._image_metadata = image_metadata
            return (FakeGlanceImageService(), 1)
        self.stubs.Set(glance, 'get_remote_image_service',
                       fake_get_remote_image_service)

        def fake_check_min_windows_version(fake_self, major, minor):
            if [major, minor] >= [6, 3]:
                return False
            return self._check_min_windows_version_satisfied
        self.stubs.Set(hostutils.HostUtils, 'check_min_windows_version',
                       fake_check_min_windows_version)

        def fake_sleep(ms):
            pass
        self.stubs.Set(time, 'sleep', fake_sleep)

        class FakeIOThread(object):
            def __init__(self, src, dest, max_bytes):
                pass

            def start(self):
                pass

        self.stubs.Set(pathutils, 'PathUtils', fake.PathUtils)
        self.stubs.Set(ioutils, 'IOThread', FakeIOThread)

        self._mox.StubOutWithMock(vmutils.VMUtils, 'get_vm_id')

        self._mox.StubOutWithMock(hostutils.HostUtils, 'get_local_ips')

        self._mox.StubOutWithMock(rdpconsoleutils.RDPConsoleUtils,
                                  'get_rdp_console_port')

        self._mox.StubOutClassWithMocks(instance_metadata, 'InstanceMetadata')
        self._mox.StubOutWithMock(instance_metadata.InstanceMetadata,
                                  'metadata_for_config_drive')

        # Can't use StubOutClassWithMocks due to __exit__ and __enter__
        self._mox.StubOutWithMock(configdrive, 'ConfigDriveBuilder')
        self._mox.StubOutWithMock(configdrive.ConfigDriveBuilder, 'make_drive')

        self._mox.StubOutWithMock(fileutils, 'delete_if_exists')
        self._mox.StubOutWithMock(utils, 'execute')

    def tearDown(self):
        self._mox.UnsetStubs()
        super(HyperVAPIBaseTestCase, self).tearDown()


class HyperVAPITestCase(HyperVAPIBaseTestCase):
    """Unit tests for Hyper-V driver calls."""

    def _get_instance_data(self):
        instance_name = 'openstack_unit_test_vm_' + str(uuid.uuid4())
        return db_fakes.get_fake_instance_data(instance_name,
                                               self._project_id,
                                               self._user_id)

    def _get_instance(self):
        updates = self._get_instance_data()
        expected_attrs = updates.pop('expected_attrs', None)
        return objects.Instance._from_db_object(
            context, objects.Instance(),
            fake_instance.fake_db_instance(**updates),
            expected_attrs=expected_attrs)

    def test_get_rdp_console(self):
        self.flags(my_ip="192.168.1.1")

        self._instance = self._get_instance()

        fake_port = 9999
        fake_vm_id = "fake_vm_id"

        m = rdpconsoleutils.RDPConsoleUtils.get_rdp_console_port()
        m.AndReturn(fake_port)

        m = vmutils.VMUtils.get_vm_id(mox.IsA(str))
        m.AndReturn(fake_vm_id)

        self._mox.ReplayAll()
        connect_info = self._conn.get_rdp_console(self._context,
                                                  self._instance)
        self._mox.VerifyAll()

        self.assertEqual(CONF.my_ip, connect_info.host)
        self.assertEqual(fake_port, connect_info.port)
        self.assertEqual(fake_vm_id, connect_info.internal_access_path)
