# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 Justin Santa Barbara
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

from nova.log import logging
from nova.tests.integrated import integrated_helpers
from nova.api.openstack import common


LOG = logging.getLogger('nova.tests.integrated')


class XmlTests(integrated_helpers._IntegratedTestBase):
    """"Some basic XML sanity checks."""

    def test_namespace_limits(self):
        """/limits should have v1.1 namespace (has changed in 1.1)."""
        headers = {}
        headers['Accept'] = 'application/xml'

        response = self.api.api_request('/limits', headers=headers)
        data = response.read()
        LOG.debug("data: %s" % data)

        prefix = '<limits xmlns="%s"' % common.XML_NS_V11
        self.assertTrue(data.startswith(prefix))

    def test_namespace_servers(self):
        """/servers should have v1.1 namespace (has changed in 1.1)."""
        headers = {}
        headers['Accept'] = 'application/xml'

        response = self.api.api_request('/servers', headers=headers)
        data = response.read()
        LOG.debug("data: %s" % data)

        prefix = '<servers xmlns="%s"' % common.XML_NS_V11
        self.assertTrue(data.startswith(prefix))
