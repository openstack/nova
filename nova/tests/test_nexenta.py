#!/usr/bin/env python
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2011 Nexenta Systems, Inc.
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
"""
Unit tests for OpenStack Nova volume driver
"""

import base64
import urllib2

import nova.flags
import nova.test
from nova.volume import nexenta
from nova.volume.nexenta import volume
from nova.volume.nexenta import jsonrpc

FLAGS = nova.flags.FLAGS


class TestNexentaDriver(nova.test.TestCase):
    TEST_VOLUME_NAME = 'volume1'
    TEST_VOLUME_NAME2 = 'volume2'
    TEST_SNAPSHOT_NAME = 'snapshot1'
    TEST_VOLUME_REF = {
        'name': TEST_VOLUME_NAME,
        'size': 1,
    }
    TEST_VOLUME_REF2 = {
        'name': TEST_VOLUME_NAME2,
        'size': 1,
    }
    TEST_SNAPSHOT_REF = {
        'name': TEST_SNAPSHOT_NAME,
        'volume_name': TEST_VOLUME_NAME,
    }

    def __init__(self, method):
        super(TestNexentaDriver, self).__init__(method)

    def setUp(self):
        super(TestNexentaDriver, self).setUp()
        self.flags(
            nexenta_host='1.1.1.1',
            nexenta_volume='nova',
            nexenta_target_prefix='iqn:',
            nexenta_target_group_prefix='nova/',
            nexenta_blocksize='8K',
            nexenta_sparse=True,
        )
        self.nms_mock = self.mox.CreateMockAnything()
        for mod in ['volume', 'zvol', 'iscsitarget',
                    'stmf', 'scsidisk', 'snapshot']:
            setattr(self.nms_mock, mod, self.mox.CreateMockAnything())
        self.stubs.Set(jsonrpc, 'NexentaJSONProxy',
                       lambda *_, **__: self.nms_mock)
        self.drv = volume.NexentaDriver()
        self.drv.do_setup({})

    def test_setup_error(self):
        self.nms_mock.volume.object_exists('nova').AndReturn(True)
        self.mox.ReplayAll()
        self.drv.check_for_setup_error()

    def test_setup_error_fail(self):
        self.nms_mock.volume.object_exists('nova').AndReturn(False)
        self.mox.ReplayAll()
        self.assertRaises(LookupError, self.drv.check_for_setup_error)

    def test_local_path(self):
        self.assertRaises(NotImplementedError, self.drv.local_path, '')

    def test_create_volume(self):
        self.nms_mock.zvol.create('nova/volume1', '1G', '8K', True)
        self.mox.ReplayAll()
        self.drv.create_volume(self.TEST_VOLUME_REF)

    def test_delete_volume(self):
        self.nms_mock.zvol.destroy('nova/volume1', '')
        self.mox.ReplayAll()
        self.drv.delete_volume(self.TEST_VOLUME_REF)

    def test_create_snapshot(self):
        self.nms_mock.zvol.create_snapshot('nova/volume1', 'snapshot1', '')
        self.mox.ReplayAll()
        self.drv.create_snapshot(self.TEST_SNAPSHOT_REF)

    def test_create_volume_from_snapshot(self):
        self.nms_mock.zvol.clone('nova/volume1@snapshot1', 'nova/volume2')
        self.mox.ReplayAll()
        self.drv.create_volume_from_snapshot(self.TEST_VOLUME_REF2,
                                             self.TEST_SNAPSHOT_REF)

    def test_delete_snapshot(self):
        self.nms_mock.snapshot.destroy('nova/volume1@snapshot1', '')
        self.mox.ReplayAll()
        self.drv.delete_snapshot(self.TEST_SNAPSHOT_REF)

    _CREATE_EXPORT_METHODS = [
        ('iscsitarget', 'create_target', ({'target_name': 'iqn:volume1'},),
            u'Unable to create iscsi target\n'
            u' iSCSI target iqn.1986-03.com.sun:02:nova-volume1 already'
                                                               u' configured\n'
            u' itadm create-target failed with error 17\n',
        ),
        ('stmf', 'create_targetgroup', ('nova/volume1',),
            u'Unable to create targetgroup: stmfadm: nova/volume1:'
                                                          u' already exists\n',
        ),
        ('stmf', 'add_targetgroup_member', ('nova/volume1', 'iqn:volume1'),
            u'Unable to add member to targetgroup: stmfadm:'
                     u' iqn.1986-03.com.sun:02:nova-volume1: already exists\n',
        ),
        ('scsidisk', 'create_lu', ('nova/volume1', {}),
            u"Unable to create lu with zvol 'nova/volume1':\n"
            u" sbdadm: filename /dev/zvol/rdsk/nova/volume1: in use\n",
        ),
        ('scsidisk', 'add_lun_mapping_entry', ('nova/volume1', {
                'target_group': 'nova/volume1', 'lun': '0'}),
            u"Unable to add view to zvol 'nova/volume1' (LUNs in use: ):\n"
            u" stmfadm: view entry exists\n",
        ),
    ]

    def _stub_export_method(self, module, method, args, error, fail=False):
        m = getattr(self.nms_mock, module)
        m = getattr(m, method)
        mock = m(*args)
        if fail:
            mock.AndRaise(nexenta.NexentaException(error))

    def _stub_all_export_methods(self, fail=False):
        for params in self._CREATE_EXPORT_METHODS:
            self._stub_export_method(*params, fail=fail)

    def test_create_export(self):
        self._stub_all_export_methods()
        self.mox.ReplayAll()
        retval = self.drv.create_export({}, self.TEST_VOLUME_REF)
        self.assertEquals(retval,
            {'provider_location':
                '%s:%s,1 %s%s' % (FLAGS.nexenta_host,
                                  FLAGS.nexenta_iscsi_target_portal_port,
                                  FLAGS.nexenta_target_prefix,
                                  self.TEST_VOLUME_NAME)})

    def __get_test(i):
        def _test_create_export_fail(self):
            for params in self._CREATE_EXPORT_METHODS[:i]:
                self._stub_export_method(*params)
            self._stub_export_method(*self._CREATE_EXPORT_METHODS[i],
                                     fail=True)
            self.mox.ReplayAll()
            self.assertRaises(nexenta.NexentaException,
                        self.drv.create_export, {}, self.TEST_VOLUME_REF)
        return _test_create_export_fail

    for i in range(len(_CREATE_EXPORT_METHODS)):
        locals()['test_create_export_fail_%d' % i] = __get_test(i)

    def test_ensure_export(self):
        self._stub_all_export_methods(fail=True)
        self.mox.ReplayAll()
        self.drv.ensure_export({}, self.TEST_VOLUME_REF)

    def test_remove_export(self):
        self.nms_mock.scsidisk.delete_lu('nova/volume1')
        self.nms_mock.stmf.destroy_targetgroup('nova/volume1')
        self.nms_mock.iscsitarget.delete_target('iqn:volume1')
        self.mox.ReplayAll()
        self.drv.remove_export({}, self.TEST_VOLUME_REF)

    def test_remove_export_fail_0(self):
        self.nms_mock.scsidisk.delete_lu('nova/volume1')
        self.nms_mock.stmf.destroy_targetgroup('nova/volume1').AndRaise(
                                                    nexenta.NexentaException())
        self.nms_mock.iscsitarget.delete_target('iqn:volume1')
        self.mox.ReplayAll()
        self.drv.remove_export({}, self.TEST_VOLUME_REF)

    def test_remove_export_fail_1(self):
        self.nms_mock.scsidisk.delete_lu('nova/volume1')
        self.nms_mock.stmf.destroy_targetgroup('nova/volume1')
        self.nms_mock.iscsitarget.delete_target('iqn:volume1').AndRaise(
                                                    nexenta.NexentaException())
        self.mox.ReplayAll()
        self.drv.remove_export({}, self.TEST_VOLUME_REF)


class TestNexentaJSONRPC(nova.test.TestCase):
    URL = 'http://example.com/'
    URL_S = 'https://example.com/'
    USER = 'user'
    PASSWORD = 'password'
    HEADERS = {'Authorization': 'Basic %s' % (base64.b64encode(
                                                ':'.join((USER, PASSWORD))),),
               'Content-Type': 'application/json'}
    REQUEST = 'the request'

    def setUp(self):
        super(TestNexentaJSONRPC, self).setUp()
        self.proxy = jsonrpc.NexentaJSONProxy(
            self.URL, self.USER, self.PASSWORD, auto=True)
        self.mox.StubOutWithMock(urllib2, 'Request', True)
        self.mox.StubOutWithMock(urllib2, 'urlopen')
        self.resp_mock = self.mox.CreateMockAnything()
        self.resp_info_mock = self.mox.CreateMockAnything()
        self.resp_mock.info().AndReturn(self.resp_info_mock)
        urllib2.urlopen(self.REQUEST).AndReturn(self.resp_mock)

    def test_call(self):
        urllib2.Request(self.URL,
                '{"object": null, "params": ["arg1", "arg2"], "method": null}',
                self.HEADERS).AndReturn(self.REQUEST)
        self.resp_info_mock.status = ''
        self.resp_mock.read().AndReturn(
                '{"error": null, "result": "the result"}')
        self.mox.ReplayAll()
        result = self.proxy('arg1', 'arg2')
        self.assertEquals("the result", result)

    def test_call_deep(self):
        urllib2.Request(self.URL,
              '{"object": "obj1.subobj", "params": ["arg1", "arg2"],'
                                                          ' "method": "meth"}',
              self.HEADERS).AndReturn(self.REQUEST)
        self.resp_info_mock.status = ''
        self.resp_mock.read().AndReturn(
            '{"error": null, "result": "the result"}')
        self.mox.ReplayAll()
        result = self.proxy.obj1.subobj.meth('arg1', 'arg2')
        self.assertEquals("the result", result)

    def test_call_auto(self):
        urllib2.Request(self.URL,
                '{"object": null, "params": ["arg1", "arg2"], "method": null}',
                self.HEADERS).AndReturn(self.REQUEST)
        urllib2.Request(self.URL_S,
                '{"object": null, "params": ["arg1", "arg2"], "method": null}',
                self.HEADERS).AndReturn(self.REQUEST)
        self.resp_info_mock.status = 'EOF in headers'
        self.resp_mock.read().AndReturn(
            '{"error": null, "result": "the result"}')
        urllib2.urlopen(self.REQUEST).AndReturn(self.resp_mock)
        self.mox.ReplayAll()
        result = self.proxy('arg1', 'arg2')
        self.assertEquals("the result", result)

    def test_call_error(self):
        urllib2.Request(self.URL,
                '{"object": null, "params": ["arg1", "arg2"], "method": null}',
                self.HEADERS).AndReturn(self.REQUEST)
        self.resp_info_mock.status = ''
        self.resp_mock.read().AndReturn(
            '{"error": {"message": "the error"}, "result": "the result"}')
        self.mox.ReplayAll()
        self.assertRaises(jsonrpc.NexentaJSONException,
                          self.proxy, 'arg1', 'arg2')

    def test_call_fail(self):
        urllib2.Request(self.URL,
                '{"object": null, "params": ["arg1", "arg2"], "method": null}',
                self.HEADERS).AndReturn(self.REQUEST)
        self.resp_info_mock.status = 'EOF in headers'
        self.proxy.auto = False
        self.mox.ReplayAll()
        self.assertRaises(jsonrpc.NexentaJSONException,
                          self.proxy, 'arg1', 'arg2')
