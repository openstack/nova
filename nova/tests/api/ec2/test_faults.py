# vim: tabstop=4 shiftwidth=4 softtabstop=4
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

import webob

from nova import test
from nova.api.ec2 import faults


class TestFaults(test.TestCase):
    """Tests covering ec2 Fault class."""

    def test_fault_exception(self):
        """Ensure the status_int is set correctly on faults"""
        fault = faults.Fault(webob.exc.HTTPBadRequest(
                             explanation='test'))
        self.assertTrue(isinstance(fault.wrapped_exc,
                         webob.exc.HTTPBadRequest))

    def test_fault_exception_status_int(self):
        """Ensure the status_int is set correctly on faults"""
        fault = faults.Fault(webob.exc.HTTPNotFound(explanation='test'))
        self.assertEquals(fault.wrapped_exc.status_int, 404)
