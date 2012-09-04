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
from nova import test
from nova.tests import fake_network
from nova.tests.image import fake
from nova.tests.integrated import integrated_helpers

FLAGS = flags.FLAGS
LOG = logging.getLogger(__name__)


class NoMatch(test.TestingException):
    pass


class ApiSampleTestBase(integrated_helpers._IntegratedTestBase):
    ctype = 'json'
    all_extensions = False
    extension_name = None

    def setUp(self):
        self.flags(use_ipv6=False,
                   osapi_compute_link_prefix=self._get_host(),
                   osapi_glance_link_prefix=self._get_glance_host())
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
            xml = etree.XML(data)
            data = etree.tostring(xml, encoding="UTF-8",
                    xml_declaration=True, pretty_print=True)
        return '\n'.join(line.rstrip() for line in data.split('\n')).strip()

    def _objectify(self, data):
        if not data:
            return {}
        if self.ctype == 'json':
            return jsonutils.loads(data)
        else:
            def to_dict(node):
                ret = {}
                if node.items():
                    ret.update(dict(node.items()))
                if node.text:
                    ret['__content__'] = node.text
                if node.tag:
                    ret['__tag__'] = node.tag
                if node.nsmap:
                    ret['__nsmap__'] = node.nsmap
                for element in node:
                    ret.setdefault(node.tag, [])
                    ret[node.tag].append(to_dict(element))
                return ret
            return to_dict(etree.fromstring(data))

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

    def _read_template(self, name):
        template = self._get_sample(name, suffix='.tpl')
        if self.generate_samples and not os.path.exists(template):
            with open(template, 'w') as outf:
                pass
        with open(template) as inf:
            return inf.read().strip()

    def _write_sample(self, name, data):
        with open(self._get_sample(name), 'w') as outf:
            outf.write(data)

    def _compare_result(self, subs, expected, result):
        matched_value = None
        if isinstance(expected, dict):
            if not isinstance(result, dict):
                raise NoMatch(
                        _('Result: %(result)s is not a dict.') % locals())
            ex_keys = sorted(expected.keys())
            res_keys = sorted(result.keys())
            if ex_keys != res_keys:
                raise NoMatch(_('Key mismatch:\n'
                        '%(ex_keys)s\n%(res_keys)s') % locals())
            for key in ex_keys:
                res = self._compare_result(subs, expected[key], result[key])
                matched_value = res or matched_value
        elif isinstance(expected, list):
            if not isinstance(result, list):
                raise NoMatch(
                        _('Result: %(result)s is not a list.') % locals())
            for ex_obj, res_obj in zip(sorted(expected), sorted(result)):
                res = self._compare_result(subs, ex_obj, res_obj)
                matched_value = res or matched_value

        elif isinstance(expected, basestring) and '%' in expected:
            try:
                # NOTE(vish): escape stuff for regex
                for char in ['[', ']', '<', '>', '?']:
                    expected = expected.replace(char, '\%s' % char)
                expected = expected % subs
                match = re.match(expected, result)
            except Exception as exc:
                raise NoMatch(_('Values do not match:\n'
                        '%(expected)s\n%(result)s') % locals())
            if not match:
                raise NoMatch(_('Values do not match:\n'
                        '%(expected)s\n%(result)s') % locals())
            if match.groups():
                matched_value = match.groups()[0]
        else:
            if expected != result:
                raise NoMatch(_('Values do not match:\n'
                        '%(expected)s\n%(result)s') % locals())
        return matched_value

    def _verify_response(self, name, subs, response):
        expected = self._read_template(name)
        expected = self._objectify(expected)
        result = self._pretty_data(response.read())
        if self.generate_samples:
            self._write_sample(name, result)
        result = self._objectify(result)
        return self._compare_result(subs, expected, result)

    def _get_host(self):
        return 'http://openstack.example.com'

    def _get_glance_host(self):
        return 'http://glance.openstack.example.com'

    def _get_regexes(self):
        if self.ctype == 'json':
            text = r'(\\"|[^"])*'
        else:
            text = r'[^<]*'
        return {
            'timestamp': '[0-9]{4}-[0,1][0-9]-[0-3][0-9]T'
                         '[0-9]{2}:[0-9]{2}:[0-9]{2}'
                         '(Z|(\+|-)[0-9]{2}:[0-9]{2})',
            'password': '[0-9a-zA-Z]{12}',
            'ip': '[0-9]{1,3}.[0-9]{1,3}.[0-9]{1,3}.[0-9]{1,3}',
            'id': '([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}'
                  '-[0-9a-f]{4}-[0-9a-f]{12})',
            'uuid': '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}'
                    '-[0-9a-f]{4}-[0-9a-f]{12}',
            'host': self._get_host(),
            'glance_host': self._get_glance_host(),
            'compute_host': self.compute.host,
            'text': text,
        }

    def _get_response(self, url, method, body=None, strip_version=False):
        headers = {}
        headers['Content-Type'] = 'application/' + self.ctype
        headers['Accept'] = 'application/' + self.ctype
        return self.api.api_request(url, body=body, method=method,
                headers=headers, strip_version=strip_version)

    def _do_get(self, url, strip_version=False):
        return self._get_response(url, 'GET', strip_version=strip_version)

    def _do_post(self, url, name, subs, method='POST'):
        body = self._read_template(name) % subs
        if self.generate_samples:
            self._write_sample(name, body)
        return self._get_response(url, method, body)

    def _do_put(self, url, name, subs):
        return self._do_post(url, name, subs, method='PUT')


class VersionsSampleJsonTest(ApiSampleTestBase):
    def test_servers_get(self):
        response = self._do_get('', strip_version=True)
        subs = self._get_regexes()
        return self._verify_response('versions-get-resp', subs, response)


class VersionsSampleXmlTest(VersionsSampleJsonTest):
    ctype = 'xml'


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


class ExtensionsSampleJsonTest(ApiSampleTestBase):
    all_extensions = True

    def test_extensions_get(self):
        response = self._do_get('extensions')
        subs = self._get_regexes()
        return self._verify_response('extensions-get-resp', subs, response)


class ExtensionsSampleXmlTest(ExtensionsSampleJsonTest):
    ctype = 'xml'


class FlavorsSampleJsonTest(ApiSampleTestBase):

    def test_flavors_get(self):
        response = self._do_get('flavors/1')
        subs = self._get_regexes()
        return self._verify_response('flavor-get-resp', subs, response)

    def test_flavors_list(self):
        response = self._do_get('flavors')
        subs = self._get_regexes()
        return self._verify_response('flavors-list-resp', subs, response)


class FlavorsSampleXmlTest(FlavorsSampleJsonTest):
    ctype = 'xml'


class FlavorsSampleAllExtensionJsonTest(FlavorsSampleJsonTest):
    all_extensions = True


class FlavorsSampleAllExtensionXmlTest(FlavorsSampleXmlTest):
    all_extensions = True


class ImagesSampleJsonTest(ApiSampleTestBase):
    def test_images_list(self):
        """Get api sample of images get list request"""
        response = self._do_get('images')
        subs = self._get_regexes()
        return self._verify_response('images-list-get-resp', subs, response)

    def test_image_get(self):
        """Get api sample of one single image details request"""
        image_id = fake.get_valid_image_id()
        response = self._do_get('images/%s' % image_id)
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        subs['image_id'] = image_id
        return self._verify_response('image-get-resp', subs, response)

    def test_images_details(self):
        """Get api sample of all images details request"""
        response = self._do_get('images/detail')
        subs = self._get_regexes()
        return self._verify_response('images-details-get-resp', subs, response)

    def test_image_metadata_get(self):
        """Get api sample of a image metadata request"""
        image_id = fake.get_valid_image_id()
        response = self._do_get('images/%s/metadata' % image_id)
        subs = self._get_regexes()
        subs['image_id'] = image_id
        return self._verify_response('image-metadata-get-resp', subs, response)

    def test_image_metadata_post(self):
        """Get api sample to update metadata of an image metadata request"""
        image_id = fake.get_valid_image_id()
        response = self._do_post(
                'images/%s/metadata' % image_id,
                'image-metadata-post-req', {})
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        return self._verify_response('image-metadata-post-resp',
                                     subs, response)

    def test_image_metadata_put(self):
        """Get api sample of image metadata put request"""
        image_id = fake.get_valid_image_id()
        response = self._do_put('images/%s/metadata' % image_id,
                                'image-metadata-put-req', {})
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        return self._verify_response('image-metadata-put-resp',
                                     subs, response)

    def test_image_meta_key_get(self):
        """Get api sample of a image metadata key request"""
        image_id = fake.get_valid_image_id()
        key = "kernel_id"
        response = self._do_get('images/%s/metadata/%s' % (image_id, key))
        subs = self._get_regexes()
        return self._verify_response('image-meta-key-get', subs, response)

    def test_image_meta_key_put(self):
        """Get api sample of image metadata key put request"""
        image_id = fake.get_valid_image_id()
        key = "auto_disk_config"
        response = self._do_put('images/%s/metadata/%s' % (image_id, key),
                                'image-meta-key-put-req', {})
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        return self._verify_response('image-meta-key-put-resp',
                                     subs,
                                     response)


class ImagesSampleXmlTest(ImagesSampleJsonTest):
    ctype = 'xml'


class LimitsSampleJsonTest(ApiSampleTestBase):
    def test_limits_get(self):
        response = self._do_get('limits')
        subs = self._get_regexes()
        return self._verify_response('limit-get-resp', subs, response)


class LimitsSampleXmlTest(LimitsSampleJsonTest):
    ctype = 'xml'
