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

import base64
import datetime
import inspect
import os
import re
import urllib
import uuid as uuid_lib

from lxml import etree

# Import extensions to pull in osapi_compute_extension CONF option used below.
from nova.api.openstack.compute import extensions
from nova.cloudpipe.pipelib import CloudPipe
from nova.compute import api
from nova import context
from nova import db
from nova.db.sqlalchemy import models
from nova.network import api
from nova.network.manager import NetworkManager
from nova.openstack.common import cfg
from nova.openstack.common import importutils
from nova.openstack.common import jsonutils
from nova.openstack.common.log import logging
from nova.openstack.common import timeutils
from nova.scheduler import driver
from nova import test
from nova.tests import fake_network
from nova.tests.image import fake
from nova.tests.integrated import integrated_helpers

CONF = cfg.CONF
CONF.import_opt('allow_resize_to_same_host', 'nova.compute.api')
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.extensions')
CONF.import_opt('vpn_image_id', 'nova.config')
CONF.import_opt('osapi_compute_link_prefix', 'nova.api.openstack.common')
CONF.import_opt('osapi_glance_link_prefix', 'nova.api.openstack.common')
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
            # NOTE(vish): allow non-quoted replacements to survive json
            data = re.sub(r'([^"])%\((.+)\)s([^"])', r'\1"%(int:\2)s"\3', data)
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
    def _get_sample_path(cls, name, dirname, suffix=''):
        parts = [dirname]
        parts.append('api_samples')
        if cls.all_extensions:
            parts.append('all_extensions')
        if cls.extension_name:
            alias = importutils.import_class(cls.extension_name).alias
            parts.append(alias)
        parts.append(name + "." + cls.ctype + suffix)
        return os.path.join(*parts)

    @classmethod
    def _get_sample(cls, name):
        dirname = os.path.dirname(os.path.abspath(__file__))
        dirname = os.path.join(dirname, "../../../doc")
        return cls._get_sample_path(name, dirname)

    @classmethod
    def _get_template(cls, name):
        dirname = os.path.dirname(os.path.abspath(__file__))
        return cls._get_sample_path(name, dirname, suffix='.tpl')

    def _read_template(self, name):
        template = self._get_template(name)
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
            if len(expected) != len(result):
                raise NoMatch(
                        _('Length mismatch: %(result)s\n%(expected)s.')
                        % locals())
            for res_obj in result:
                for ex_obj in expected:
                    try:
                        res = self._compare_result(subs, ex_obj, res_obj)
                        break
                    except NoMatch:
                        pass
                else:
                    raise NoMatch(
                            _('Result: %(res_obj)s not in %(expected)s.')
                            % locals())
                matched_value = res or matched_value

        elif isinstance(expected, basestring) and '%' in expected:
            # NOTE(vish): escape stuff for regex
            for char in '[]<>?':
                expected = expected.replace(char, '\\%s' % char)
            # NOTE(vish): special handling of subs that are not quoted. We are
            #             expecting an int but we had to pass in a string
            #             so the json would parse properly.
            if expected.startswith("%(int:"):
                result = str(result)
                expected = expected.replace('int:', '')
            expected = expected % subs
            expected = '^%s$' % expected
            match = re.match(expected, result)
            if not match:
                raise NoMatch(_('Values do not match:\n'
                        '%(expected)s\n%(result)s') % locals())
            try:
                matched_value = match.group('id')
            except IndexError:
                if match.groups():
                    matched_value = match.groups()[0]
        else:
            if isinstance(expected, basestring):
                # NOTE(danms): Ignore whitespace in this comparison
                expected = expected.strip()
                result = result.strip()
            if expected != result:
                raise NoMatch(_('Values do not match:\n'
                        '%(expected)s\n%(result)s') % locals())
        return matched_value

    def _verify_something(self, subs, expected, data):
        result = self._pretty_data(data)
        result = self._objectify(result)
        return self._compare_result(subs, expected, result)

    def generalize_subs(self, subs, vanilla_regexes):
        """Give the test a chance to modify subs after the server response
        was verified, and before the on-disk doc/api_samples file is checked.
        This may be needed by some tests to convert exact matches expected
        from the server into pattern matches to verify what is in the
        sample file.

        If there are no changes to be made, subs is returned unharmed.
        """
        return subs

    def _verify_response(self, name, subs, response):
        expected = self._read_template(name)
        expected = self._objectify(expected)
        response_data = response.read()
        try:
            with file(self._get_sample(name)) as sample:
                sample_data = sample.read()
        except IOError:
            sample_data = "{}"

        try:
            response_result = self._verify_something(subs, expected,
                                                     response_data)
            # NOTE(danms): replace some of the subs with patterns for the
            # doc/api_samples check, which won't have things like the
            # correct compute host name. Also let the test do some of its
            # own generalization, if necessary
            vanilla_regexes = self._get_regexes()
            subs['compute_host'] = vanilla_regexes['host_name']
            subs['id'] = vanilla_regexes['id']
            subs = self.generalize_subs(subs, vanilla_regexes)
            self._verify_something(subs, expected, sample_data)
            return response_result
        except NoMatch:
            if self.generate_samples:
                self._write_sample(name, self._pretty_data(response_data))
            raise

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
            # NOTE(treinish): Could result in a false positive, but it
            # shouldn't be an issue for this case.
            'timestamp': '\d{4}-[0,1]\d-[0-3]\d[ ,T]'
                         '\d{2}:\d{2}:\d{2}'
                         '(Z|(\+|-)\d{2}:\d{2}|\.\d{6})',
            'password': '[0-9a-zA-Z]{1,12}',
            'ip': '[0-9]{1,3}.[0-9]{1,3}.[0-9]{1,3}.[0-9]{1,3}',
            'ip6': '([0-9a-zA-Z]{1,4}:){1,7}:?[0-9a-zA-Z]{1,4}',
            'id': '(?P<id>[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}'
                  '-[0-9a-f]{4}-[0-9a-f]{12})',
            'uuid': '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}'
                    '-[0-9a-f]{4}-[0-9a-f]{12}',
            'reservation_id': 'r-[0-9a-zA-Z]{8}',
            'private_key': '-----BEGIN RSA PRIVATE KEY-----'
                           '[a-zA-Z0-9\n/+=]*'
                           '-----END RSA PRIVATE KEY-----',
            'public_key': 'ssh-rsa[ a-zA-Z0-9/+=]*'
                          'Generated by Nova',
            'fingerprint': '([0-9a-f]{2}:){15}[0-9a-f]{2}',
#            '[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:'
#                           '[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:'
#                           '[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:'
#                           '[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}:[0-9a-f]{2}',
            'host': self._get_host(),
            'host_name': '[0-9a-z]{32}',
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
        sample = self._get_sample(name)
        if self.generate_samples and not os.path.exists(sample):
                self._write_sample(name, body)
        return self._get_response(url, method, body)

    def _do_put(self, url, name, subs):
        return self._do_post(url, name, subs, method='PUT')

    def _do_delete(self, url):
        return self._get_response(url, 'DELETE')


class ApiSamplesTrap(ApiSampleTestBase):
    """Make sure extensions don't get added without tests"""

    all_extensions = True

    def _get_extensions_tested(self):
        tests = []
        for attr in globals().values():
            if not inspect.isclass(attr):
                continue  # Skip non-class objects
            if not issubclass(attr, integrated_helpers._IntegratedTestBase):
                continue  # Skip non-test classes
            if attr.extension_name is None:
                continue  # Skip base tests
            cls = importutils.import_class(attr.extension_name)
            tests.append(cls.alias)
        return tests

    def _get_extensions(self):
        extensions = []
        response = self._do_get('extensions')
        for extension in jsonutils.loads(response.read())['extensions']:
            extensions.append(str(extension['alias']))
        return extensions

    def test_all_extensions_have_samples(self):
        # NOTE(danms): This is a list of extensions which are currently
        # in the tree but that don't (yet) have tests. This list should
        # NOT be allowed to grow, and should shrink to zero (and be
        # removed) soon.
        do_not_approve_additions = []
        do_not_approve_additions.append('NMN')
        do_not_approve_additions.append('OS-FLV-DISABLED')
        do_not_approve_additions.append('os-config-drive')
        do_not_approve_additions.append('os-coverage')
        do_not_approve_additions.append('os-create-server-ext')
        do_not_approve_additions.append('os-fixed-ips')
        do_not_approve_additions.append('os-flavor-access')
        do_not_approve_additions.append('os-flavor-extra-specs')
        do_not_approve_additions.append('os-flavor-rxtx')
        do_not_approve_additions.append('os-flavor-swap')
        do_not_approve_additions.append('os-floating-ip-dns')
        do_not_approve_additions.append('os-floating-ip-pools')
        do_not_approve_additions.append('os-fping')
        do_not_approve_additions.append('os-hypervisors')
        do_not_approve_additions.append('os-instance_usage_audit_log')
        do_not_approve_additions.append('os-networks')
        do_not_approve_additions.append('os-quota-class-sets')
        do_not_approve_additions.append('os-services')
        do_not_approve_additions.append('os-volumes')

        tests = self._get_extensions_tested()
        extensions = self._get_extensions()
        missing_tests = []
        for extension in extensions:
            # NOTE(danms): if you add tests, remove it from the
            # exclusions list
            self.assertFalse(extension in do_not_approve_additions and
                             extension in tests)

            # NOTE(danms): if you add an extension, it must come with
            # api_samples tests!
            if (extension not in tests and
                extension not in do_not_approve_additions):
                missing_tests.append(extension)

        if missing_tests:
            LOG.error("Extensions are missing tests: %s" % missing_tests)
        self.assertEqual(missing_tests, [])


class VersionsSampleJsonTest(ApiSampleTestBase):
    def test_versions_get(self):
        response = self._do_get('', strip_version=True)
        subs = self._get_regexes()
        return self._verify_response('versions-get-resp', subs, response)


class VersionsSampleXmlTest(VersionsSampleJsonTest):
    ctype = 'xml'


class ServersSampleBase(ApiSampleTestBase):
    def _post_server(self):
        subs = {
            'image_id': fake.get_valid_image_id(),
            'host': self._get_host(),
        }
        response = self._do_post('servers', 'server-post-req', subs)
        self.assertEqual(response.status, 202)
        subs = self._get_regexes()
        return self._verify_response('server-post-resp', subs, response)


class ServersSampleJsonTest(ServersSampleBase):
    def test_servers_post(self):
        return self._post_server()

    def test_servers_get(self):
        uuid = self.test_servers_post()
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['hypervisor_hostname'] = r'[\w\.\-]+'
        return self._verify_response('server-get-resp', subs, response)

    def test_servers_list(self):
        uuid = self._post_server()
        response = self._do_get('servers')
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        subs['id'] = uuid
        return self._verify_response('servers-list-resp', subs, response)

    def test_servers_details(self):
        uuid = self._post_server()
        response = self._do_get('servers/detail')
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['hypervisor_hostname'] = r'[\w\.\-]+'
        return self._verify_response('servers-details-resp', subs, response)


class ServersSampleXmlTest(ServersSampleJsonTest):
    ctype = 'xml'


class ServersSampleAllExtensionJsonTest(ServersSampleJsonTest):
    all_extensions = True


class ServersSampleAllExtensionXmlTest(ServersSampleXmlTest):
    all_extensions = True


class ServersSampleHideAddressesJsonTest(ServersSampleJsonTest):
    extension_name = '.'.join(('nova.api.openstack.compute.contrib',
                               'hide_server_addresses',
                               'Hide_server_addresses'))


class ServersSampleHideAddressesXMLTest(ServersSampleHideAddressesJsonTest):
    ctype = 'xml'


class ServersMetadataJsonTest(ServersSampleBase):
    def _create_and_set(self, subs):
        uuid = self._post_server()
        response = self._do_put('servers/%s/metadata' % uuid,
                                'server-metadata-all-req',
                                subs)
        self.assertEqual(response.status, 200)
        self._verify_response('server-metadata-all-resp', subs, response)

        return uuid

    def generalize_subs(self, subs, vanilla_regexes):
        subs['value'] = '(Foo|Bar) Value'
        return subs

    def test_metadata_put_all(self):
        """Test setting all metadata for a server"""
        subs = {'value': 'Foo Value'}
        return self._create_and_set(subs)

    def test_metadata_post_all(self):
        """Test updating all metadata for a server"""
        subs = {'value': 'Foo Value'}
        uuid = self._create_and_set(subs)
        subs['value'] = 'Bar Value'
        response = self._do_post('servers/%s/metadata' % uuid,
                                 'server-metadata-all-req',
                                 subs)
        self.assertEqual(response.status, 200)
        self._verify_response('server-metadata-all-resp', subs, response)

    def test_metadata_get_all(self):
        """Test getting all metadata for a server"""
        subs = {'value': 'Foo Value'}
        uuid = self._create_and_set(subs)
        response = self._do_get('servers/%s/metadata' % uuid)
        self.assertEqual(response.status, 200)
        self._verify_response('server-metadata-all-resp', subs, response)

    def test_metadata_put(self):
        """Test putting an individual metadata item for a server"""
        subs = {'value': 'Foo Value'}
        uuid = self._create_and_set(subs)
        subs['value'] = 'Bar Value'
        response = self._do_put('servers/%s/metadata/foo' % uuid,
                                'server-metadata-req',
                                subs)
        self.assertEqual(response.status, 200)
        return self._verify_response('server-metadata-resp', subs, response)

    def test_metadata_get(self):
        """Test getting an individual metadata item for a server"""
        subs = {'value': 'Foo Value'}
        uuid = self._create_and_set(subs)
        response = self._do_get('servers/%s/metadata/foo' % uuid)
        self.assertEqual(response.status, 200)
        return self._verify_response('server-metadata-resp', subs, response)

    def test_metadata_delete(self):
        """Test deleting an individual metadata item for a server"""
        subs = {'value': 'Foo Value'}
        uuid = self._create_and_set(subs)
        response = self._do_delete('servers/%s/metadata/foo' % uuid)
        self.assertEqual(response.status, 204)
        self.assertEqual(response.read(), '')


class ServersMetadataXmlTest(ServersMetadataJsonTest):
    ctype = 'xml'


class ServersIpsJsonTest(ServersSampleBase):
    def test_get(self):
        """Test getting a server's IP information"""
        uuid = self._post_server()
        response = self._do_get('servers/%s/ips' % uuid)
        subs = self._get_regexes()
        return self._verify_response('server-ips-resp', subs, response)

    def test_get_by_network(self):
        """Test getting a server's IP information by network id"""
        uuid = self._post_server()
        response = self._do_get('servers/%s/ips/private' % uuid)
        subs = self._get_regexes()
        return self._verify_response('server-ips-network-resp', subs, response)


class ServersIpsXmlTest(ServersIpsJsonTest):
    ctype = 'xml'


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


class HostsSampleJsonTest(ApiSampleTestBase):
    extension_name = "nova.api.openstack.compute.contrib.hosts.Hosts"

    def test_host_startup(self):
        response = self._do_get('os-hosts/%s/startup' % self.compute.host)
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        return self._verify_response('host-get-startup', subs, response)

    def test_host_reboot(self):
        response = self._do_get('os-hosts/%s/reboot' % self.compute.host)
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        return self._verify_response('host-get-reboot', subs, response)

    def test_host_shutdown(self):
        response = self._do_get('os-hosts/%s/shutdown' % self.compute.host)
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        return self._verify_response('host-get-shutdown', subs, response)

    def test_host_maintenance(self):
        response = self._do_put('os-hosts/%s' % self.compute.host,
                                'host-put-maintenance-req', {})
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        return self._verify_response('host-put-maintenance-resp', subs,
                                     response)

    def test_host_get(self):
        response = self._do_get('os-hosts/%s' % self.compute.host)
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        return self._verify_response('host-get-resp', subs, response)

    def test_hosts_list(self):
        response = self._do_get('os-hosts')
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        return self._verify_response('hosts-list-resp', subs, response)


class HostsSampleXmlTest(HostsSampleJsonTest):
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


class ServersActionsJsonTest(ServersSampleBase):
    def _test_server_action(self, uuid, action,
                            subs={}, resp_tpl=None, code=202):
        subs.update({'action': action})
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-action-%s' % action.lower(),
                                 subs)
        self.assertEqual(response.status, code)
        if resp_tpl:
            subs.update(self._get_regexes())
            return self._verify_response(resp_tpl, subs, response)
        else:
            self.assertEqual(response.read(), "")

    def test_server_password(self):
        uuid = self._post_server()
        self._test_server_action(uuid, "changePassword",
                                 {"password": "foo"})

    def test_server_reboot(self):
        uuid = self._post_server()
        self._test_server_action(uuid, "reboot",
                                 {"type": "HARD"})
        self._test_server_action(uuid, "reboot",
                                 {"type": "SOFT"})

    def test_server_rebuild(self):
        uuid = self._post_server()
        image = self.api.get_images()[0]['id']
        subs = {'host': self._get_host(),
                'uuid': image,
                'name': 'foobar',
                'pass': 'seekr3t',
                'ip': '1.2.3.4',
                'ip6': 'fe80::100',
                'hostid': '[a-f0-9]+',
                }
        self._test_server_action(uuid, 'rebuild', subs,
                                 'server-action-rebuild-resp')

    def test_server_resize(self):
        self.flags(allow_resize_to_same_host=True)
        uuid = self._post_server()
        self._test_server_action(uuid, "resize",
                                 {"id": 2,
                                  "host": self._get_host()})
        return uuid

    def test_server_revert_resize(self):
        uuid = self.test_server_resize()
        self._test_server_action(uuid, "revertResize")

    def test_server_confirm_resize(self):
        uuid = self.test_server_resize()
        self._test_server_action(uuid, "confirmResize", code=204)

    def test_server_create_image(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'createImage',
                                 {'name': 'foo-image',
                                  'meta_var': 'myvar',
                                  'meta_val': 'foobar'})


class ServersActionsXmlTest(ServersActionsJsonTest):
    ctype = 'xml'


class ServersActionsAllJsonTest(ServersActionsJsonTest):
    all_extensions = True


class ServersActionsAllXmlTest(ServersActionsXmlTest):
    all_extensions = True


class ServerStartStopJsonTest(ServersSampleBase):
    extension_name = "nova.api.openstack.compute.contrib" + \
        ".server_start_stop.Server_start_stop"

    def _test_server_action(self, uuid, action):
        response = self._do_post('servers/%s/action' % uuid,
                                 'server_start_stop',
                                 {'action': action})
        self.assertEqual(response.status, 202)
        self.assertEqual(response.read(), "")

    def test_server_start(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'os-stop')
        self._test_server_action(uuid, 'os-start')

    def test_server_stop(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'os-stop')


class ServerStartStopXmlTest(ServerStartStopJsonTest):
    ctype = 'xml'


class UserDataJsonTest(ApiSampleTestBase):
    extension_name = "nova.api.openstack.compute.contrib.user_data.User_data"

    def test_user_data_post(self):
        user_data_contents = '#!/bin/bash\n/bin/su\necho "I am in you!"\n'
        user_data = base64.b64encode(user_data_contents)
        subs = {
            'image_id': fake.get_valid_image_id(),
            'host': self._get_host(),
            'user_data': user_data
            }
        response = self._do_post('servers', 'userdata-post-req', subs)

        self.assertEqual(response.status, 202)
        subs.update(self._get_regexes())
        return self._verify_response('userdata-post-resp', subs, response)


class UserDataXmlTest(UserDataJsonTest):
    ctype = 'xml'


class FlavorsExtraDataJsonTest(ApiSampleTestBase):
    extension_name = ('nova.api.openstack.compute.contrib.flavorextradata.'
                      'Flavorextradata')

    def _get_flags(self):
        f = super(FlavorsExtraDataJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        # Flavorextradata extension also needs Flavormanage to be loaded.
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.flavormanage.Flavormanage')
        return f

    def test_flavors_extra_data_get(self):
        flavor_id = 1
        response = self._do_get('flavors/%s' % flavor_id)
        self.assertEqual(response.status, 200)
        subs = {
            'flavor_id': flavor_id,
            'flavor_name': 'm1.tiny'
        }
        subs.update(self._get_regexes())
        return self._verify_response('flavors-extra-data-get-resp', subs,
                                     response)

    def test_flavors_extra_data_list(self):
        response = self._do_get('flavors/detail')
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        return self._verify_response('flavors-extra-data-list-resp', subs,
                                     response)

    def test_flavors_extra_data_create(self):
        subs = {
            'flavor_id': 666,
            'flavor_name': 'flavortest'
        }
        response = self._do_post('flavors',
                                 'flavors-extra-data-post-req',
                                 subs)
        self.assertEqual(response.status, 200)
        subs.update(self._get_regexes())
        return self._verify_response('flavors-extra-data-post-resp',
                                     subs, response)


class FlavorsExtraDataXmlTest(FlavorsExtraDataJsonTest):
    ctype = 'xml'


class SecurityGroupsSampleJsonTest(ServersSampleBase):
    extension_name = "nova.api.openstack.compute.contrib" + \
                     ".security_groups.Security_groups"

    def test_security_group_create(self):
        name = self.ctype + '-test'
        subs = {
                'group_name': name,
                "description": "description",
        }
        response = self._do_post('os-security-groups',
                                 'security-group-post-req', subs)
        self.assertEqual(response.status, 200)
        self._verify_response('security-groups-create-resp', subs, response)

    def test_security_groups_list(self):
        """Get api sample of security groups get list request"""
        response = self._do_get('os-security-groups')
        subs = self._get_regexes()
        return self._verify_response('security-groups-list-get-resp',
                                      subs, response)

    def test_security_groups_get(self):
        """Get api sample of security groups get request"""
        security_group_id = '1'
        response = self._do_get('os-security-groups/%s' % security_group_id)
        subs = self._get_regexes()
        return self._verify_response('security-groups-get-resp',
                                      subs, response)

    def test_security_groups_list_server(self):
        """Get api sample of security groups for a specific server."""
        uuid = self._post_server()
        response = self._do_get('servers/%s/os-security-groups' % uuid)
        subs = self._get_regexes()
        return self._verify_response('server-security-groups-list-resp',
                                      subs, response)


class SecurityGroupsSampleXmlTest(SecurityGroupsSampleJsonTest):
    ctype = 'xml'


class SchedulerHintsJsonTest(ApiSampleTestBase):
    extension_name = ("nova.api.openstack.compute.contrib.scheduler_hints."
                     "Scheduler_hints")

    def test_scheduler_hints_post(self):
        """Get api sample of scheduler hint post request"""
        hints = {'image_id': fake.get_valid_image_id(),
                 'image_near': str(uuid_lib.uuid4())
        }
        response = self._do_post('servers', 'scheduler-hints-post-req',
                                 hints)
        self.assertEqual(response.status, 202)
        subs = self._get_regexes()
        return self._verify_response('scheduler-hints-post-resp', subs,
                                     response)


class SchedulerHintsXmlTest(SchedulerHintsJsonTest):
    ctype = 'xml'


class ConsoleOutputSampleJsonTest(ServersSampleBase):
    extension_name = "nova.api.openstack.compute.contrib" + \
                                     ".console_output.Console_output"

    def test_get_console_output(self):
        uuid = self._post_server()
        response = self._do_post('servers/%s/action' % uuid,
                                 'console-output-post-req',
                                {'action': 'os-getConsoleOutput'})
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        return self._verify_response('console-output-post-resp',
                                       subs, response)


class ConsoleOutputSampleXmlTest(ConsoleOutputSampleJsonTest):
        ctype = 'xml'


class ExtendedServerAttributesJsonTest(ServersSampleBase):
    extension_name = "nova.api.openstack.compute.contrib" + \
                     ".extended_server_attributes" + \
                     ".Extended_server_attributes"

    def test_extended_server_attrs_get(self):
        uuid = self._post_server()

        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['instance_name'] = 'instance-\d{8}'
        subs['hypervisor_hostname'] = r'[\w\.\-]+'
        return self._verify_response('extended-server-attrs-get',
                                     subs, response)

    def test_extended_server_attrs_list(self):
        uuid = self._post_server()

        response = self._do_get('servers/detail')
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['instance_name'] = 'instance-\d{8}'
        subs['hypervisor_hostname'] = r'[\w\.\-]+'
        return self._verify_response('extended-server-attrs-list',
                                     subs, response)


class ExtendedServerAttributesXmlTest(ExtendedServerAttributesJsonTest):
    ctype = 'xml'


class FloatingIpsJsonTest(ApiSampleTestBase):
    extension_name = "nova.api.openstack.compute.contrib." \
        "floating_ips.Floating_ips"

    def setUp(self):
        super(FloatingIpsJsonTest, self).setUp()
        pool = CONF.default_floating_pool
        interface = CONF.public_interface

        self.ip_pool = [
            {
                'address': "10.10.10.1",
                'pool': pool,
                'interface': interface
                },
            {
                'address': "10.10.10.2",
                'pool': pool,
                'interface': interface
                },
            {
                'address': "10.10.10.3",
                'pool': pool,
                'interface': interface
                },
            ]
        self.compute.db.floating_ip_bulk_create(
            context.get_admin_context(), self.ip_pool)

    def tearDown(self):
        self.compute.db.floating_ip_bulk_destroy(
            context.get_admin_context(), self.ip_pool)
        super(FloatingIpsJsonTest, self).tearDown()

    def test_floating_ips_list_empty(self):
        response = self._do_get('os-floating-ips')

        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        return self._verify_response('floating-ips-list-empty-resp',
                                     subs, response)

    def test_floating_ips_list(self):
        self._do_post('os-floating-ips',
                      'floating-ips-create-nopool-req',
                      {})
        self._do_post('os-floating-ips',
                      'floating-ips-create-nopool-req',
                      {})

        response = self._do_get('os-floating-ips')
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        return self._verify_response('floating-ips-list-resp',
                                     subs, response)

    def test_floating_ips_create_nopool(self):
        response = self._do_post('os-floating-ips',
                                 'floating-ips-create-nopool-req',
                                 {})
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        self._verify_response('floating-ips-create-resp',
                              subs, response)

    def test_floating_ips_create(self):
        response = self._do_post('os-floating-ips',
                                 'floating-ips-create-req',
                                 {"pool": CONF.default_floating_pool})
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        self._verify_response('floating-ips-create-resp',
                              subs, response)

    def test_floating_ips_get(self):
        self.test_floating_ips_create()
        # NOTE(sdague): the first floating ip will always have 1 as an id,
        # but it would be better if we could get this from the create
        response = self._do_get('os-floating-ips/%d' % 1)
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        self._verify_response('floating-ips-create-resp',
                              subs, response)

    def test_floating_ips_delete(self):
        self.test_floating_ips_create()
        response = self._do_delete('os-floating-ips/%d' % 1)
        self.assertEqual(response.status, 202)


class FloatingIpsXmlTest(FloatingIpsJsonTest):
    ctype = 'xml'


class FloatingIpsBulkJsonTest(ApiSampleTestBase):
    extension_name = "nova.api.openstack.compute.contrib." \
        "floating_ips_bulk.Floating_ips_bulk"

    def setUp(self):
        super(FloatingIpsBulkJsonTest, self).setUp()
        pool = CONF.default_floating_pool
        interface = CONF.public_interface

        self.ip_pool = [
            {
                'address': "10.10.10.1",
                'pool': pool,
                'interface': interface
                },
            {
                'address': "10.10.10.2",
                'pool': pool,
                'interface': interface
                },
            {
                'address': "10.10.10.3",
                'pool': pool,
                'interface': interface,
                'host': "testHost"
                },
            ]
        self.compute.db.floating_ip_bulk_create(
            context.get_admin_context(), self.ip_pool)

    def tearDown(self):
        self.compute.db.floating_ip_bulk_destroy(
            context.get_admin_context(), self.ip_pool)
        super(FloatingIpsBulkJsonTest, self).tearDown()

    def test_floating_ips_bulk_list(self):
        response = self._do_get('os-floating-ips-bulk')
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        return self._verify_response('floating-ips-bulk-list-resp', subs,
                                     response)

    def test_floating_ips_bulk_list_by_host(self):
        response = self._do_get('os-floating-ips-bulk/testHost')
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        return self._verify_response('floating-ips-bulk-list-by-host-resp',
                                     subs, response)

    def test_floating_ips_bulk_create(self):
        response = self._do_post('os-floating-ips-bulk',
                                 'floating-ips-bulk-create-req',
                                 {"ip_range": "192.168.1.0/24",
                                  "pool": CONF.default_floating_pool,
                                  "interface": CONF.public_interface})
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        return self._verify_response('floating-ips-bulk-create-resp', subs,
                                     response)

    def test_floating_ips_bulk_delete(self):
        response = self._do_put('os-floating-ips-bulk/delete',
                                'floating-ips-bulk-delete-req',
                                {"ip_range": "192.168.1.0/24"})
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        return self._verify_response('floating-ips-bulk-delete-resp', subs,
                                     response)


class FloatingIpsBulkXmlTest(FloatingIpsBulkJsonTest):
    ctype = 'xml'


class KeyPairsSampleJsonTest(ApiSampleTestBase):
    extension_name = "nova.api.openstack.compute.contrib.keypairs.Keypairs"

    def generalize_subs(self, subs, vanilla_regexes):
        subs['keypair_name'] = 'keypair-[0-9a-f-]+'
        return subs

    def test_keypairs_post(self, public_key=None):
        """Get api sample of key pairs post request"""
        key_name = 'keypair-' + str(uuid_lib.uuid4())
        response = self._do_post('os-keypairs', 'keypairs-post-req',
                                 {'keypair_name': key_name})
        subs = self._get_regexes()
        subs['keypair_name'] = '(%s)' % key_name
        self.assertEqual(response.status, 200)
        self._verify_response('keypairs-post-resp', subs, response)
        # NOTE(maurosr): return the key_name is necessary cause the
        # verification returns the label of the last compared information in
        # the response, not necessarily the key name.
        return key_name

    def test_keypairs_import_key_post(self):
        """Get api sample of key pairs post to import user's key"""
        key_name = 'keypair-' + str(uuid_lib.uuid4())
        subs = {
            'keypair_name': key_name,
            'public_key': "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQDx8nkQv/zgGg"
                          "B4rMYmIf+6A4l6Rr+o/6lHBQdW5aYd44bd8JttDCE/F/pNRr0l"
                          "RE+PiqSPO8nDPHw0010JeMH9gYgnnFlyY3/OcJ02RhIPyyxYpv"
                          "9FhY+2YiUkpwFOcLImyrxEsYXpD/0d3ac30bNH6Sw9JD9UZHYc"
                          "pSxsIbECHw== Generated by Nova"
        }
        response = self._do_post('os-keypairs', 'keypairs-import-post-req',
                                 subs)
        subs = self._get_regexes()
        subs['keypair_name'] = '(%s)' % key_name
        self.assertEqual(response.status, 200)
        self._verify_response('keypairs-import-post-resp', subs, response)

    def test_keypairs_get(self):
        """Get api sample of key pairs get request"""
        key_name = self.test_keypairs_post()
        response = self._do_get('os-keypairs')
        subs = self._get_regexes()
        subs['keypair_name'] = '(%s)' % key_name
        return self._verify_response('keypairs-get-resp', subs, response)


class KeyPairsSampleXmlTest(KeyPairsSampleJsonTest):
    ctype = 'xml'


class RescueJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                     ".rescue.Rescue")

    def _rescue(self, uuid):
        req_subs = {
            'password': 'MySecretPass'
        }
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-rescue-req', req_subs)
        self._verify_response('server-rescue', req_subs, response)

    def _unrescue(self, uuid):
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-unrescue-req', {})
        self.assertEqual(response.status, 202)

    def test_server_rescue(self):
        uuid = self._post_server()

        self._rescue(uuid)

        # Do a server get to make sure that the 'RESCUE' state is set
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['status'] = 'RESCUE'

        self._verify_response('server-get-resp-rescue', subs, response)

    def test_server_unrescue(self):
        uuid = self._post_server()

        self._rescue(uuid)
        self._unrescue(uuid)

        # Do a server get to make sure that the 'ACTIVE' state is back
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['status'] = 'ACTIVE'

        self._verify_response('server-get-resp-unrescue', subs, response)


class RescueXmlTest(RescueJsonTest):
    ctype = 'xml'


class VirtualInterfacesJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                     ".virtual_interfaces.Virtual_interfaces")

    def test_vifs_list(self):
        uuid = self._post_server()

        response = self._do_get('servers/%s/os-virtual-interfaces' % uuid)
        self.assertEqual(response.status, 200)

        subs = self._get_regexes()
        subs['mac_addr'] = '(?:[a-f0-9]{2}:){5}[a-f0-9]{2}'

        self._verify_response('vifs-list-resp', subs, response)


class VirtualInterfacesXmlTest(VirtualInterfacesJsonTest):
    ctype = 'xml'


class CloudPipeSampleJsonTest(ApiSampleTestBase):
    extension_name = "nova.api.openstack.compute.contrib.cloudpipe.Cloudpipe"

    def setUp(self):
        super(CloudPipeSampleJsonTest, self).setUp()

        def get_user_data(self, project_id):
            """Stub method to generate user data for cloudpipe tests"""
            return "VVNFUiBEQVRB\n"

        def network_api_get(self, context, network_uuid):
            """Stub to get a valid network and its information"""
            return {'vpn_public_address': '127.0.0.1',
                    'vpn_public_port': 22}

        self.stubs.Set(CloudPipe, 'get_encoded_zip', get_user_data)
        self.stubs.Set(NetworkManager, "get_network", network_api_get)

    def generalize_subs(self, subs, vanilla_regexes):
        subs['project_id'] = 'cloudpipe-[0-9a-f-]+'
        return subs

    def test_cloud_pipe_create(self):
        """Get api samples of cloud pipe extension creation"""
        self.flags(vpn_image_id=fake.get_valid_image_id())
        project = {'project_id': 'cloudpipe-' + str(uuid_lib.uuid4())}
        response = self._do_post('os-cloudpipe', 'cloud-pipe-create-req',
                                 project)
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        subs.update(project)
        subs['image_id'] = CONF.vpn_image_id
        self._verify_response('cloud-pipe-create-resp', subs, response)
        return project

    def test_cloud_pipe_list(self):
        """Get api samples of cloud pipe extension get request"""
        project = self.test_cloud_pipe_create()
        response = self._do_get('os-cloudpipe')
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        subs.update(project)
        subs['image_id'] = CONF.vpn_image_id
        return self._verify_response('cloud-pipe-get-resp', subs, response)


class CloudPipeSampleXmlTest(CloudPipeSampleJsonTest):
    ctype = "xml"


class CloudPipeUpdateJsonTest(ApiSampleTestBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                      ".cloudpipe_update.Cloudpipe_update")

    def _get_flags(self):
        f = super(CloudPipeUpdateJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        # Cloudpipe_update also needs cloudpipe to be loaded
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.cloudpipe.Cloudpipe')
        return f

    def setUp(self):
        super(CloudPipeUpdateJsonTest, self).setUp()

    def test_cloud_pipe_update(self):
        subs = {'vpn_ip': '192.168.1.1',
                'vpn_port': 2000}
        response = self._do_put('os-cloudpipe/configure-project',
                                'cloud-pipe-update-req',
                                subs)
        self.assertEqual(response.status, 202)


class CloudPipeUpdateXmlTest(CloudPipeUpdateJsonTest):
    ctype = "xml"


class AgentsJsonTest(ApiSampleTestBase):
    extension_name = "nova.api.openstack.compute.contrib.agents.Agents"

    def _get_flags(self):
        f = super(AgentsJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        return f

    def setUp(self):
        super(AgentsJsonTest, self).setUp()

        fake_agents_list = [{'url': 'xxxxxxxxxxxx',
                             'hypervisor': 'hypervisor',
                             'architecture': 'x86',
                             'os': 'os',
                             'version': '8.0',
                             'md5hash': 'add6bb58e139be103324d04d82d8f545',
                             'id': '1'}]

        def fake_agent_build_create(context, values):
            values['id'] = '1'
            agent_build_ref = models.AgentBuild()
            agent_build_ref.update(values)
            return agent_build_ref

        def fake_agent_build_get_all(context, hypervisor):
            agent_build_all = []
            for agent in fake_agents_list:
                if hypervisor and hypervisor != agent['hypervisor']:
                    continue
                agent_build_ref = models.AgentBuild()
                agent_build_ref.update(agent)
                agent_build_all.append(agent_build_ref)
            return agent_build_all

        def fake_agent_build_update(context, agent_build_id, values):
            pass

        def fake_agent_build_destroy(context, agent_update_id):
            pass

        self.stubs.Set(db, "agent_build_create",
                       fake_agent_build_create)
        self.stubs.Set(db, "agent_build_get_all",
                       fake_agent_build_get_all)
        self.stubs.Set(db, "agent_build_update",
                       fake_agent_build_update)
        self.stubs.Set(db, "agent_build_destroy",
                       fake_agent_build_destroy)

    def test_agent_create(self):
        """Creates a new agent build."""
        project = {'url': 'xxxxxxxxxxxx',
                'hypervisor': 'hypervisor',
                'architecture': 'x86',
                'os': 'os',
                'version': '8.0',
                'md5hash': 'add6bb58e139be103324d04d82d8f545'
                }
        response = self._do_post('os-agents', 'agent-post-req',
                                 project)
        self.assertEqual(response.status, 200)
        project['agent_id'] = 1
        self._verify_response('agent-post-resp', project, response)
        return project

    def test_agent_list(self):
        """ Return a list of all agent builds."""
        response = self._do_get('os-agents')
        self.assertEqual(response.status, 200)
        project = {'url': 'xxxxxxxxxxxx',
                'hypervisor': 'hypervisor',
                'architecture': 'x86',
                'os': 'os',
                'version': '8.0',
                'md5hash': 'add6bb58e139be103324d04d82d8f545',
                'agent_id': 1
                }
        return self._verify_response('agents-get-resp', project, response)

    def test_agent_update(self):
        """Update an existing agent build."""
        agent_id = 1
        subs = {'version': '7.0',
                'url': 'xxx://xxxx/xxx/xxx',
                'md5hash': 'add6bb58e139be103324d04d82d8f545'}
        response = self._do_put('os-agents/%s' % agent_id,
                                'agent-update-put-req', subs)
        self.assertEqual(response.status, 200)
        subs['agent_id'] = 1
        return self._verify_response('agent-update-put-resp', subs, response)

    def test_agent_delete(self):
        """Deletes an existing agent build."""
        agent_id = 1
        response = self._do_delete('os-agents/%s' % agent_id)
        self.assertEqual(response.status, 200)


class AgentsXmlTest(AgentsJsonTest):
    ctype = "xml"


class AggregatesSampleJsonTest(ServersSampleBase):
    extension_name = "nova.api.openstack.compute.contrib" + \
                                     ".aggregates.Aggregates"

    def test_aggregate_create(self):
        subs = {
            "aggregate_id": '(?P<id>\d+)'
        }
        response = self._do_post('os-aggregates', 'aggregate-post-req', subs)
        self.assertEqual(response.status, 200)
        subs.update(self._get_regexes())
        return self._verify_response('aggregate-post-resp', subs, response)

    def test_list_aggregates(self):
        self.test_aggregate_create()
        response = self._do_get('os-aggregates')
        subs = self._get_regexes()
        return self._verify_response('aggregates-list-get-resp',
                                      subs, response)

    def test_aggregate_get(self):
        agg_id = self.test_aggregate_create()
        response = self._do_get('os-aggregates/%s' % agg_id)
        subs = self._get_regexes()
        return self._verify_response('aggregates-get-resp', subs, response)

    def test_add_metadata(self):
        agg_id = self.test_aggregate_create()
        response = self._do_post('os-aggregates/%s/action' % agg_id,
                                 'aggregate-metadata-post-req',
                                 {'action': 'set_metadata'})
        subs = self._get_regexes()
        return self._verify_response('aggregates-metadata-post-resp',
                                      subs, response)

    def test_add_host(self):
        aggregate_id = self.test_aggregate_create()
        subs = {
            "host_name": self.compute.host,
        }
        response = self._do_post('os-aggregates/%s/action' % aggregate_id,
                                 'aggregate-add-host-post-req', subs)
        subs.update(self._get_regexes())
        return self._verify_response('aggregates-add-host-post-resp',
                                      subs, response)

    def test_remove_host(self):
        self.test_add_host()
        subs = {
            "host_name": self.compute.host,
        }
        response = self._do_post('os-aggregates/1/action',
                                 'aggregate-remove-host-post-req', subs)
        subs.update(self._get_regexes())
        return self._verify_response('aggregates-remove-host-post-resp',
                                      subs, response)

    def test_update_aggregate(self):
        aggregate_id = self.test_aggregate_create()
        response = self._do_put('os-aggregates/%s' % aggregate_id,
                                  'aggregate-update-post-req', {})
        subs = self._get_regexes()
        return self._verify_response('aggregate-update-post-resp',
                                      subs, response)


class AggregatesSampleXmlTest(AggregatesSampleJsonTest):
    ctype = 'xml'


class CertificatesSamplesJsonTest(ApiSampleTestBase):
    extension_name = ("nova.api.openstack.compute.contrib.certificates."
                      "Certificates")

    def setUp(self):
        super(CertificatesSamplesJsonTest, self).setUp()

    def test_create_certificates(self):
        response = self._do_post('os-certificates',
                                 'certificate-create-req', {})
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        return self._verify_response('certificate-create-resp', subs, response)

    def test_get_root_certificate(self):
        response = self._do_get('os-certificates/root')
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        return self._verify_response('certificate-get-root-resp', subs,
                                     response)


class CertificatesSamplesXmlTest(CertificatesSamplesJsonTest):
    ctype = 'xml'


class UsedLimitsSamplesJsonTest(ApiSampleTestBase):
    extension_name = ("nova.api.openstack.compute.contrib.used_limits."
                      "Used_limits")

    def test_get_used_limits(self):
        """Get api sample to used limits"""
        response = self._do_get('limits')
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        return self._verify_response('usedlimits-get-resp', subs, response)


class UsedLimitsSamplesXmlTest(UsedLimitsSamplesJsonTest):
    ctype = "xml"


class MultipleCreateJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib.multiple_create."
                      "Multiple_create")

    def test_multiple_create(self):
        subs = {
            'image_id': fake.get_valid_image_id(),
            'host': self._get_host(),
            'min_count': "2",
            'max_count': "3"
        }
        response = self._do_post('servers', 'multiple-create-post-req', subs)
        self.assertEqual(response.status, 202)
        subs.update(self._get_regexes())
        return self._verify_response('multiple-create-post-resp',
                                      subs, response)

    def test_multiple_create_without_reservation_id(self):
        subs = {
            'image_id': fake.get_valid_image_id(),
            'host': self._get_host(),
            'min_count': "2",
            'max_count': "3"
        }
        response = self._do_post('servers', 'multiple-create-no-resv-post-req',
                                  subs)
        self.assertEqual(response.status, 202)
        subs.update(self._get_regexes())
        return self._verify_response('multiple-create-no-resv-post-resp',
                                      subs, response)


class MultipleCreateXmlTest(MultipleCreateJsonTest):
    ctype = 'xml'


class SimpleTenantUsageSampleJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib.simple_tenant_usage."
                      "Simple_tenant_usage")

    def setUp(self):
        """setUp method for simple tenant usage"""
        super(SimpleTenantUsageSampleJsonTest, self).setUp()
        self._post_server()
        timeutils.set_time_override(timeutils.utcnow() +
                                    datetime.timedelta(hours=1))
        self.query = {
            'start': str(timeutils.utcnow() - datetime.timedelta(hours=1)),
            'end': str(timeutils.utcnow())
        }

    def tearDown(self):
        """tearDown method for simple tenant usage"""
        super(SimpleTenantUsageSampleJsonTest, self).tearDown()
        timeutils.clear_time_override()

    def test_get_tenants_usage(self):
        """Get api sample to get all tenants usage request"""
        response = self._do_get('os-simple-tenant-usage?%s' % (
                                                urllib.urlencode(self.query)))
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        self._verify_response('simple-tenant-usage-get', subs, response)

    def test_get_tenant_usage_details(self):
        """Get api sample to get specific tenant usage request"""
        tenant_id = 'openstack'
        response = self._do_get('os-simple-tenant-usage/%s?%s' % (tenant_id,
                                                urllib.urlencode(self.query)))
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        self._verify_response('simple-tenant-usage-get-specific', subs,
                              response)


class SimpleTenantUsageSampleXmlTest(SimpleTenantUsageSampleJsonTest):
    ctype = "xml"


class ServerDiagnosticsSamplesJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib.server_diagnostics."
                      "Server_diagnostics")

    def test_server_diagnostics_get(self):
        uuid = self._post_server()
        response = self._do_get('servers/%s/diagnostics' % uuid)
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        return self._verify_response('server-diagnostics-get-resp', subs,
                                     response)


class ServerDiagnosticsSamplesXmlTest(ServerDiagnosticsSamplesJsonTest):
    ctype = "xml"


class AvailabilityZoneJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib.availability_zone."
                      "Availability_zone")

    def test_create_availability_zone(self):
        subs = {
            'image_id': fake.get_valid_image_id(),
            'host': self._get_host(),
            "availability_zone": "nova"
        }
        response = self._do_post('servers', 'availability-zone-post-req', subs)
        self.assertEqual(response.status, 202)
        subs.update(self._get_regexes())
        return self._verify_response('availability-zone-post-resp',
                                      subs, response)


class AvailabilityZoneXmlTest(AvailabilityZoneJsonTest):
    ctype = "xml"


class AdminActionsSamplesJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib.admin_actions."
                      "Admin_actions")

    def setUp(self):
        """setUp Method for AdminActions api samples extension
        This method creates the server that will be used in each tests"""
        super(AdminActionsSamplesJsonTest, self).setUp()
        self.uuid = self._post_server()

    def test_post_pause(self):
        """Get api samples to pause server request"""
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-pause', {})
        self.assertEqual(response.status, 202)

    def test_post_unpause(self):
        """Get api samples to unpause server request"""
        self.test_post_pause()
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-unpause', {})
        self.assertEqual(response.status, 202)

    def test_post_suspend(self):
        """Get api samples to suspend server request"""
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-suspend', {})
        self.assertEqual(response.status, 202)

    def test_post_resume(self):
        """Get api samples to server resume request"""
        self.test_post_suspend()
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-resume', {})
        self.assertEqual(response.status, 202)

    def test_post_migrate(self):
        """Get api samples to migrate server request"""
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-migrate', {})
        self.assertEqual(response.status, 202)

    def test_post_reset_network(self):
        """Get api samples to reset server network request"""
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-reset-network', {})
        self.assertEqual(response.status, 202)

    def test_post_inject_network_info(self):
        """Get api samples to inject network info request"""
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-inject-network-info', {})
        self.assertEqual(response.status, 202)

    def test_post_lock_server(self):
        """Get api samples to lock server request"""
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-lock-server', {})
        self.assertEqual(response.status, 202)

    def test_post_unlock_server(self):
        """Get api samples to unlock server request"""
        self.test_post_lock_server()
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-unlock-server', {})
        self.assertEqual(response.status, 202)

    def test_post_backup_server(self):
        """Get api samples to backup server request"""
        def image_details(self, context, **kwargs):
            """This stub is specifically used on the backup action."""
            # NOTE(maurosr): I've added this simple stub cause backup action
            # was trapped in infinite loop during fetch image phase since the
            # fake Image Service always returns the same set of images
            return None

        self.stubs.Set(fake._FakeImageService, 'detail', image_details)

        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-backup-server', {})
        self.assertEqual(response.status, 202)

    def test_post_live_migrate_server(self):
        """Get api samples to server live migrate request"""
        def fake_live_migration_src_check(self, context, instance_ref):
            """Skip live migration scheduler checks"""
            return

        def fake_live_migration_dest_check(self, context, instance_ref, dest):
            """Skip live migration scheduler checks"""
            return

        def fake_live_migration_common(self, context, instance_ref, dest):
            """Skip live migration scheduler checks"""
            return
        self.stubs.Set(driver.Scheduler, '_live_migration_src_check',
                       fake_live_migration_src_check)
        self.stubs.Set(driver.Scheduler, '_live_migration_dest_check',
                       fake_live_migration_dest_check)
        self.stubs.Set(driver.Scheduler, '_live_migration_common_check',
                       fake_live_migration_common)

        def fake_get_compute(context, host):
            service = dict(host=host,
                           binary='nova-compute',
                           topic='compute',
                           report_count=1,
                           updated_at='foo',
                           hypervisor_type='bar',
                           hypervisor_version='1',
                           disabled=False)
            return [{'compute_node': [service]}]
        self.stubs.Set(db, "service_get_all_compute_by_host", fake_get_compute)

        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-live-migrate',
                                 {'hostname': self.compute.host})
        self.assertEqual(response.status, 202)

    def test_post_reset_state(self):
        """get api samples to server reset state request"""
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'admin-actions-reset-server-state', {})
        self.assertEqual(response.status, 202)


class AdminActionsSamplesXmlTest(AdminActionsSamplesJsonTest):
    ctype = 'xml'


class ConsolesSampleJsonTests(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                                     ".consoles.Consoles")

    def test_get_vnc_console(self):
        uuid = self._post_server()
        response = self._do_post('servers/%s/action' % uuid,
                                 'get-vnc-console-post-req',
                                {'action': 'os-getVNCConsole'})
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        subs["url"] = \
            "((https?):((//)|(\\\\))+([\w\d:#@%/;$()~_?\+-=\\\.&](#!)?)*)"
        return self._verify_response('get-vnc-console-post-resp',
                                       subs, response)


class ConsolesSampleXmlTests(ConsolesSampleJsonTests):
        ctype = 'xml'


class DeferredDeleteSampleJsonTests(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                                     ".deferred_delete.Deferred_delete")

    def setUp(self):
        super(DeferredDeleteSampleJsonTests, self).setUp()
        self.flags(reclaim_instance_interval=1)

    def test_restore(self):
        uuid = self._post_server()
        response = self._do_delete('servers/%s' % uuid)

        response = self._do_post('servers/%s/action' % uuid,
                                 'restore-post-req', {})
        self.assertEqual(response.status, 202)
        self.assertEqual(response.read(), '')

    def test_force_delete(self):
        uuid = self._post_server()
        response = self._do_delete('servers/%s' % uuid)

        response = self._do_post('servers/%s/action' % uuid,
                                 'force-delete-post-req', {})
        self.assertEqual(response.status, 202)
        self.assertEqual(response.read(), '')


class DeferredDeleteSampleXmlTests(DeferredDeleteSampleJsonTests):
        ctype = 'xml'


class QuotasSampleJsonTests(ApiSampleTestBase):
    extension_name = "nova.api.openstack.compute.contrib.quotas.Quotas"

    def test_show_quotas(self):
        """Get api sample to show quotas"""
        response = self._do_get('os-quota-sets/fake_tenant')
        self.assertEqual(response.status, 200)
        return self._verify_response('quotas-show-get-resp', {}, response)

    def test_show_quotas_defaults(self):
        """Get api sample to show quotas defaults"""
        response = self._do_get('os-quota-sets/fake_tenant/defaults')
        self.assertEqual(response.status, 200)
        return self._verify_response('quotas-show-defaults-get-resp',
                                     {}, response)

    def test_update_quotas(self):
        """Get api sample to update quotas"""
        response = self._do_put('os-quota-sets/fake_tenant',
                                'quotas-update-post-req',
                                {})
        self.assertEqual(response.status, 200)
        return self._verify_response('quotas-update-post-resp', {}, response)


class QuotasSampleXmlTests(QuotasSampleJsonTests):
    ctype = "xml"


class ExtendedStatusSampleJsonTests(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                                     ".extended_status.Extended_status")

    def test_show(self):
        uuid = self._post_server()
        response = self._do_get('servers')
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        subs['id'] = uuid
        return self._verify_response('servers-list-resp', subs, response)

    def test_detail(self):
        uuid = self._post_server()
        response = self._do_get('servers/detail')
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        subs['id'] = uuid
        subs['hostid'] = '[a-f0-9]+'
        return self._verify_response('servers-detail-resp', subs, response)


class ExtendedStatusSampleXmlTests(ExtendedStatusSampleJsonTests):
        ctype = 'xml'


class FlavorManageSampleJsonTests(ApiSampleTestBase):
    extension_name = ("nova.api.openstack.compute.contrib.flavormanage."
                      "Flavormanage")

    def _create_flavor(self):
        """Create a flavor"""
        subs = {
            'flavor_id': 10,
            'flavor_name': "test_flavor"
        }
        response = self._do_post("flavors",
                                 "flavor-create-post-req",
                                 subs)
        self.assertEqual(response.status, 200)
        subs.update(self._get_regexes())
        return self._verify_response("flavor-create-post-resp", subs, response)

    def test_create_flavor(self):
        """Get api sample to create a flavor"""
        self._create_flavor()

    def test_delete_flavor(self):
        """Get api sample to delete a flavor"""
        self._create_flavor()
        response = self._do_delete("flavors/10")
        self.assertEqual(response.status, 202)
        self.assertEqual(response.read(), '')


class FlavorManageSampleXmlTests(FlavorManageSampleJsonTests):
    ctype = "xml"


class DiskConfigJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib.disk_config."
                      "Disk_config")

    def test_list_servers_detail(self):
        uuid = self._post_server()
        response = self._do_get('servers/detail')
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        return self._verify_response('list-servers-detail-get',
                                     subs, response)

    def test_get_server(self):
        uuid = self._post_server()
        response = self._do_get('servers/%s' % uuid)
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        return self._verify_response('server-get-resp', subs, response)

    def test_update_server(self):
        uuid = self._post_server()
        response = self._do_put('servers/%s' % uuid,
                                'server-update-put-req', {})
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        return self._verify_response('server-update-put-resp',
                                      subs, response)

    def test_resize_server(self):
        self.flags(allow_resize_to_same_host=True)
        uuid = self._post_server()
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-resize-post-req', {})
        self.assertEqual(response.status, 202)
        # NOTE(tmello): Resize does not return response body
        # Bug #1085213.
        self.assertEqual(response.read(), "")

    def test_rebuild_server(self):
        uuid = self._post_server()
        subs = {
            'image_id': fake.get_valid_image_id(),
            'host': self._get_host(),
        }
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-action-rebuild-req', subs)
        self.assertEqual(response.status, 202)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        return self._verify_response('server-action-rebuild-resp',
                                      subs, response)

    def test_get_image(self):
        image_id = fake.get_valid_image_id()
        response = self._do_get('images/%s' % image_id)
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        subs['image_id'] = image_id
        return self._verify_response('image-get-resp', subs, response)

    def test_list_images(self):
        response = self._do_get('images/detail')
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
        return self._verify_response('image-list-resp', subs, response)


class DiskConfigXmlTest(DiskConfigJsonTest):
        ctype = 'xml'


class NetworksAssociateJsonTests(ApiSampleTestBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                                     ".networks_associate.Networks_associate")

    _sentinel = object()

    def _get_flags(self):
        f = super(NetworksAssociateJsonTests, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        # Networks_associate requires Networks to be update
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.networks.Networks')
        return f

    def setUp(self):
        super(NetworksAssociateJsonTests, self).setUp()

        def fake_associate(self, context, network_id,
                           host=NetworksAssociateJsonTests._sentinel,
                           project=NetworksAssociateJsonTests._sentinel):
            return True

        self.stubs.Set(api.API, "associate", fake_associate)

    def test_disassociate(self):
        response = self._do_post('os-networks/1/action',
                                 'network-disassociate-req',
                                 {})
        self.assertEqual(response.status, 202)

    def test_disassociate_host(self):
        response = self._do_post('os-networks/1/action',
                                 'network-disassociate-host-req',
                                 {})
        self.assertEqual(response.status, 202)

    def test_disassociate_project(self):
        response = self._do_post('os-networks/1/action',
                                 'network-disassociate-project-req',
                                 {})
        self.assertEqual(response.status, 202)

    def test_associate_host(self):
        response = self._do_post('os-networks/1/action',
                                 'network-associate-host-req',
                                 {"host": "testHost"})
        self.assertEqual(response.status, 202)


class NetworksAssociateXmlTests(NetworksAssociateJsonTests):
    ctype = 'xml'
