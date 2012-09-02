# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 NetApp, Inc.
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
"""Unit tests for the NetApp-specific NFS driver module (netapp_nfs)"""

from nova import context
from nova import exception
from nova import test

from nova.volume import netapp
from nova.volume import netapp_nfs
from nova.volume import nfs

from mox import IgnoreArg
from mox import IsA
from mox import MockObject

import mox
import suds
import types


class FakeVolume(object):
    def __init__(self, size=0):
        self.size = size
        self.id = hash(self)
        self.name = None

    def __getitem__(self, key):
        return self.__dict__[key]


class FakeSnapshot(object):
    def __init__(self, volume_size=0):
        self.volume_name = None
        self.name = None
        self.volume_id = None
        self.volume_size = volume_size
        self.user_id = None
        self.status = None

    def __getitem__(self, key):
        return self.__dict__[key]


class FakeResponce(object):
    def __init__(self, status):
        """
        :param status: Either 'failed' or 'passed'
        """
        self.Status = status

        if status == 'failed':
            self.Reason = 'Sample error'


class NetappNfsDriverTestCase(test.TestCase):
    """Test case for NetApp specific NFS clone driver"""

    def setUp(self):
        self._driver = netapp_nfs.NetAppNFSDriver()
        self._mox = mox.Mox()

    def tearDown(self):
        self._mox.UnsetStubs()

    def test_check_for_setup_error(self):
        mox = self._mox
        drv = self._driver
        required_flags = [
                'netapp_wsdl_url',
                'netapp_login',
                'netapp_password',
                'netapp_server_hostname',
                'netapp_server_port'
            ]

        # check exception raises when flags are not set
        self.assertRaises(exception.NovaException,
                          drv.check_for_setup_error)

        # set required flags
        for flag in required_flags:
            setattr(netapp.FLAGS, flag, 'val')

        mox.StubOutWithMock(nfs.NfsDriver, 'check_for_setup_error')
        nfs.NfsDriver.check_for_setup_error()
        mox.ReplayAll()

        drv.check_for_setup_error()

        mox.VerifyAll()

        # restore initial FLAGS
        for flag in required_flags:
            delattr(netapp.FLAGS, flag)

    def test_do_setup(self):
        mox = self._mox
        drv = self._driver

        mox.StubOutWithMock(drv, 'check_for_setup_error')
        mox.StubOutWithMock(netapp_nfs.NetAppNFSDriver, '_get_client')

        drv.check_for_setup_error()
        netapp_nfs.NetAppNFSDriver._get_client()

        mox.ReplayAll()

        drv.do_setup(IsA(context.RequestContext))

        mox.VerifyAll()

    def test_create_snapshot(self):
        """Test snapshot can be created and deleted"""
        mox = self._mox
        drv = self._driver

        mox.StubOutWithMock(drv, '_clone_volume')
        drv._clone_volume(IgnoreArg(), IgnoreArg(), IgnoreArg())
        mox.ReplayAll()

        drv.create_snapshot(FakeSnapshot())

        mox.VerifyAll()

    def test_create_volume_from_snapshot(self):
        """Tests volume creation from snapshot"""
        drv = self._driver
        mox = self._mox
        volume = FakeVolume(1)
        snapshot = FakeSnapshot(2)

        self.assertRaises(exception.NovaException,
                          drv.create_volume_from_snapshot,
                          volume,
                          snapshot)

        snapshot = FakeSnapshot(1)

        location = '127.0.0.1:/nfs'
        expected_result = {'provider_location': location}
        mox.StubOutWithMock(drv, '_clone_volume')
        mox.StubOutWithMock(drv, '_get_volume_location')
        drv._clone_volume(IgnoreArg(), IgnoreArg(), IgnoreArg())
        drv._get_volume_location(IgnoreArg()).AndReturn(location)

        mox.ReplayAll()

        loc = drv.create_volume_from_snapshot(volume, snapshot)

        self.assertEquals(loc, expected_result)

        mox.VerifyAll()

    def _prepare_delete_snapshot_mock(self, snapshot_exists):
        drv = self._driver
        mox = self._mox

        mox.StubOutWithMock(drv, '_get_provider_location')
        mox.StubOutWithMock(drv, '_volume_not_present')

        if snapshot_exists:
            mox.StubOutWithMock(drv, '_execute')
            mox.StubOutWithMock(drv, '_get_volume_path')

        drv._get_provider_location(IgnoreArg())
        drv._volume_not_present(IgnoreArg(), IgnoreArg())\
                                        .AndReturn(not snapshot_exists)

        if snapshot_exists:
            drv._get_volume_path(IgnoreArg(), IgnoreArg())
            drv._execute('rm', None, run_as_root=True)

        mox.ReplayAll()

        return mox

    def test_delete_existing_snapshot(self):
        drv = self._driver
        mox = self._prepare_delete_snapshot_mock(True)

        drv.delete_snapshot(FakeSnapshot())

        mox.VerifyAll()

    def test_delete_missing_snapshot(self):
        drv = self._driver
        mox = self._prepare_delete_snapshot_mock(False)

        drv.delete_snapshot(FakeSnapshot())

        mox.VerifyAll()

    def _prepare_clone_mock(self, status):
        drv = self._driver
        mox = self._mox

        volume = FakeVolume()
        setattr(volume, 'provider_location', '127.0.0.1:/nfs')

        drv._client = MockObject(suds.client.Client)
        drv._client.factory = MockObject(suds.client.Factory)
        drv._client.service = MockObject(suds.client.ServiceSelector)

        # ApiProxy() method is generated by ServiceSelector at runtime from the
        # XML, so mocking is impossible.
        setattr(drv._client.service,
                'ApiProxy',
                types.MethodType(lambda *args, **kwargs: FakeResponce(status),
                                 suds.client.ServiceSelector))
        mox.StubOutWithMock(drv, '_get_host_id')
        mox.StubOutWithMock(drv, '_get_full_export_path')

        drv._get_host_id(IgnoreArg()).AndReturn('10')
        drv._get_full_export_path(IgnoreArg(), IgnoreArg()).AndReturn('/nfs')

        return mox

    def test_successfull_clone_volume(self):
        drv = self._driver
        mox = self._prepare_clone_mock('passed')

        mox.ReplayAll()

        volume_name = 'volume_name'
        clone_name = 'clone_name'
        volume_id = volume_name + str(hash(volume_name))

        drv._clone_volume(volume_name, clone_name, volume_id)

        mox.VerifyAll()

    def test_failed_clone_volume(self):
        drv = self._driver
        mox = self._prepare_clone_mock('failed')

        mox.ReplayAll()

        volume_name = 'volume_name'
        clone_name = 'clone_name'
        volume_id = volume_name + str(hash(volume_name))

        self.assertRaises(exception.NovaException,
                          drv._clone_volume,
                          volume_name, clone_name, volume_id)

        mox.VerifyAll()
