# vim: tabstop=4 shiftwidth=4 softtabstop=4
# Copyright 2012 Nebula, Inc.
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

import os
import re

from lxml import etree

from nova import flags
from nova.openstack.common import jsonutils
from nova.openstack.common.log import logging
from nova.tests import fake_network
from nova.tests.image import fake
from nova.tests.integrated import integrated_helpers

FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)


class ApiSampleTestBase(integrated_helpers._IntegratedTestBase):
    ctype = 'json'
    all_extensions = False
    extension_name = None

    def setUp(self):
        self.flags(use_ipv6=False,
                   osapi_compute_link_prefix=self._get_host())
        if not self.all_extensions:
            ext = [self.extension_name] if self.extension_name else []
            self.flags(osapi_compute_extension=ext)
        super(ApiSampleTestBase, self).setUp()
        fake_network.stub_compute_with_ips(self.stubs)
        self.generate_samples = os.getenv('GENERATE_SAMPLES') is not None

    def _pretty_data(self, data):
        if self.ctype == 'json':
            data = jsonutils.dumps(jsonutils.loads(data), sort_keys=True,
                    indent=4)

        else:
            data = etree.tostring(etree.XML(data), encoding="UTF-8",
                    xml_declaration=True, pretty_print=True)
        return '\n'.join(line.rstrip() for line in data.split('\n'))

    @classmethod
    def _get_sample(cls, name, suffix=''):
        parts = [os.path.dirname(os.path.abspath(__file__))]
        parts.append('api_samples')
        if cls.all_extensions:
            parts.append('all_extensions')
        if cls.extension_name:
            parts.append(cls.extension_name)
        parts.append(name + "." + cls.ctype + suffix)
        return os.path.join(*parts)

    @classmethod
    def _get_template(cls, name):
        return cls._get_sample(name, suffix='.tpl')

    def _read_template(self, name):
        with open(self._get_template(name)) as inf:
            return inf.read().strip()

    def _write_sample(self, name, data):
        with open(self._get_sample(name), 'w') as outf:
            outf.write(data)

    def _verify_response(self, name, subs, response):
        expected = self._read_template(name)

        # NOTE(vish): escape stuff for regex
        for char in ['[', ']', '<', '>', '?']:
            expected = expected.replace(char, '\%s' % char)

        expected = expected % subs
        data = response.read()
        result = self._pretty_data(data).strip()
        if self.generate_samples:
            self._write_sample(name, result)
        result_lines = result.split('\n')
        expected_lines = expected.split('\n')
        if len(result_lines) != len(expected_lines):
            LOG.info(expected)
            LOG.info(result)
            self.fail('Number of lines (%s) incorrect' % (len(expected_lines)))
        result = None
        for line, result_line in zip(expected_lines, result_lines):
            try:
                match = re.match(line, result_line)
            except Exception as exc:
                self.fail(_('Response error on line:\n'
                          '%(line)s\n%(result_line)s') % locals())
            if not match:
                self.fail(_('Response error on line:\n'
                          '%(line)s\n%(result_line)s') % locals())
            if match.groups():
                result = match.groups()[0]
        return result

    def _get_host(self):
        return 'http://openstack.example.com'

    def _get_regexes(self):
        return {
            'timestamp': '[0-9]{4}-[0,1][0-9]-[0-3][0-9]T'
                         '[0-9]{2}:[0-9]{2}:[0-9]{2}Z',
            'password': '[0-9a-zA-Z]{12}',
            'ip': '[0-9]{1,3}.[0-9]{1,3}.[0-9]{1,3}.[0-9]{1,3}',
            'id': '([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}'
                  '-[0-9a-f]{4}-[0-9a-f]{12})',
            'uuid': '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}'
                    '-[0-9a-f]{4}-[0-9a-f]{12}',
            'host': self._get_host(),
            'compute_host': self.compute.host,
        }

    def _get_response(self, url, method, body=None):
        headers = {}
        headers['Content-Type'] = 'application/' + self.ctype
        headers['Accept'] = 'application/' + self.ctype
        return self.api.api_request(url, body=body, method=method,
                headers=headers)

    def _do_get(self, url):
        return self._get_response(url, 'GET')

    def _do_post(self, url, name, subs):
        body = self._read_template(name) % subs
        if self.generate_samples:
            self._write_sample(name, self._pretty_data(body))
        return self._get_response(url, 'POST', body)


class ServersSampleJsonTest(ApiSampleTestBase):
    def test_servers_post(self):
        subs = {
            'image_id': fake.get_valid_image_id(),
            'host': self._get_host(),
        }
        response = self._do_post('servers', 'server-post-req', subs)
        self.assertEqual(response.status, 202)
        subs = self._get_regexes()
        return self._verify_response('server-post-resp', subs, response)

    def test_servers_get(self):
        uuid = self.test_servers_post()
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        return self._verify_response('server-get-resp', subs, response)


class ServersSampleXmlTest(ServersSampleJsonTest):
    ctype = 'xml'


class ServersSampleAllExtensionJsonTest(ServersSampleJsonTest):
    all_extensions = True


class ServersSampleAllExtensionXmlTest(ServersSampleXmlTest):
    all_extensions = True
