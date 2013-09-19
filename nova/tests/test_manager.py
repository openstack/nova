# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (C) 2013, Red Hat, Inc.
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
Unit Tests for nova.manager
"""

from nova import manager
from nova import test


class ManagerTestCase(test.NoDBTestCase):
    def test_additional_apis_for_dispatcher(self):
        class MyAPI(object):
            pass

        m = manager.Manager()
        api = MyAPI()
        dispatch = m.create_rpc_dispatcher(additional_apis=[api])

        self.assertEqual(len(dispatch.callbacks), 3)
        self.assertTrue(api in dispatch.callbacks)
