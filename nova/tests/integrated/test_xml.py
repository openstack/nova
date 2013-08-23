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

from lxml import etree

from nova.api.openstack import common
from nova.api.openstack import xmlutil
from nova.openstack.common import log as logging
from nova.tests.integrated.api import client
from nova.tests.integrated import integrated_helpers


LOG = logging.getLogger(__name__)


class XmlTests(integrated_helpers._IntegratedTestBase):
    """"Some basic XML sanity checks."""

    _api_version = 'v2'

    def test_namespace_limits(self):
        headers = {}
        headers['Accept'] = 'application/xml'

        response = self.api.api_request('/limits', headers=headers)
        data = response.read()
        LOG.debug("data: %s" % data)
        root = etree.XML(data)
        self.assertEqual(root.nsmap.get(None), xmlutil.XMLNS_COMMON_V10)

    def test_namespace_servers(self):
        # /servers should have v1.1 namespace (has changed in 1.1).
        headers = {}
        headers['Accept'] = 'application/xml'

        response = self.api.api_request('/servers', headers=headers)
        data = response.read()
        LOG.debug("data: %s" % data)
        root = etree.XML(data)
        self.assertEqual(root.nsmap.get(None), common.XML_NS_V11)


class XmlTestsV3(client.TestOpenStackClientV3Mixin, XmlTests):
    _api_version = 'v3'
