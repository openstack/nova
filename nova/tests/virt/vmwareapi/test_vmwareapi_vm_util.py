# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2013 Canonical Corp.
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

from nova import exception
from nova import test
from nova.virt.vmwareapi import fake
from nova.virt.vmwareapi import vm_util


class fake_session(object):
    def __init__(self, ret=None):
        self.ret = ret

    def _call_method(self, *args):
        return self.ret


class VMwareVMUtilTestCase(test.TestCase):
    def setUp(self):
        super(VMwareVMUtilTestCase, self).setUp()

    def tearDown(self):
        super(VMwareVMUtilTestCase, self).tearDown()

    def test_get_datastore_ref_and_name(self):
        result = vm_util.get_datastore_ref_and_name(
            fake_session([fake.Datastore()]))

        self.assertEquals(result[1], "fake-ds")
        self.assertEquals(result[2], 1024 * 1024 * 1024)
        self.assertEquals(result[3], 1024 * 1024 * 500)

    def test_get_datastore_ref_and_name_without_datastore(self):

        self.assertRaises(exception.DatastoreNotFound,
                vm_util.get_datastore_ref_and_name,
                fake_session(), host="fake-host")

        self.assertRaises(exception.DatastoreNotFound,
                vm_util.get_datastore_ref_and_name,
                fake_session(), cluster="fake-cluster")
