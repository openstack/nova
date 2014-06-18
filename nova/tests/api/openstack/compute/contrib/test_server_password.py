# Copyright 2012 Nebula, Inc.
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
from oslo.config import cfg
import webob

from nova.api.metadata import password
from nova import compute
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_instance


CONF = cfg.CONF
CONF.import_opt('osapi_compute_ext_list', 'nova.api.openstack.compute.contrib')


class ServerPasswordTest(test.TestCase):
    content_type = 'application/json'

    def setUp(self):
        super(ServerPasswordTest, self).setUp()
        fakes.stub_out_nw_api(self.stubs)
        self.stubs.Set(
            compute.api.API, 'get',
            lambda self, ctxt, *a, **kw:
                fake_instance.fake_instance_obj(
                ctxt,
                system_metadata={},
                expected_attrs=['system_metadata']))
        self.password = 'fakepass'

        def fake_extract_password(instance):
            return self.password

        def fake_convert_password(context, password):
            self.password = password
            return {}

        self.stubs.Set(password, 'extract_password', fake_extract_password)
        self.stubs.Set(password, 'convert_password', fake_convert_password)
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Server_password'])

    def _make_request(self, url, method='GET'):
        req = webob.Request.blank(url)
        req.headers['Accept'] = self.content_type
        req.method = method
        res = req.get_response(
                fakes.wsgi_app(init_only=('servers', 'os-server-password')))
        return res

    def _get_pass(self, body):
        return jsonutils.loads(body).get('password')

    def test_get_password(self):
        url = '/v2/fake/servers/fake/os-server-password'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        self.assertEqual(self._get_pass(res.body), 'fakepass')

    def test_reset_password(self):
        url = '/v2/fake/servers/fake/os-server-password'
        res = self._make_request(url, 'DELETE')
        self.assertEqual(res.status_int, 204)

        res = self._make_request(url)
        self.assertEqual(res.status_int, 200)
        self.assertEqual(self._get_pass(res.body), '')


class ServerPasswordXmlTest(ServerPasswordTest):
    content_type = 'application/xml'

    def _get_pass(self, body):
        # NOTE(vish): first element is password
        return etree.XML(body).text or ''
