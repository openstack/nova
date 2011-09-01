# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
#    Copyright 2010 OpenStack LLC
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

from nova import db
from nova import test
from nova.tests import utils as test_utils


class TestUtilsTestCase(test.TestCase):
    def test_get_test_admin_context(self):
        """get_test_admin_context's return value behaves like admin context"""
        ctxt = test_utils.get_test_admin_context()

        # TODO(soren): This should verify the full interface context
        # objects expose.
        self.assertTrue(ctxt.is_admin)

    def test_get_test_instance(self):
        """get_test_instance's return value looks like an instance_ref"""
        instance_ref = test_utils.get_test_instance()
        ctxt = test_utils.get_test_admin_context()
        db.instance_get(ctxt, instance_ref['id'])

    def _test_get_test_network_info(self):
        """Does the return value match a real network_info structure"""
        # The challenge here is to define what exactly such a structure
        # must look like.
        pass
