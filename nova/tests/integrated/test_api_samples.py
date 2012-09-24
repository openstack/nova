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
import os
import re
import uuid

from lxml import etree

from nova import context
from nova import flags
from nova.openstack.common import importutils
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
            # NOTE(maurosr): sort the list of dicts by their __tag__ element
            # when using xml. This will avoid some fails in keypairs api sample
            # which order in different way when using a private key itself or
            # its regular expression, and after all doesn't interfere with
            # other tests.
            # Should we define a criteria when ordering json? Doesn't seems
            # necessary so far.
            for ex_obj, res_obj in zip(sorted(expected, key=lambda k:
                                                        k.get('__tag__', k)),
                                       sorted(result, key=lambda k:
                                                        k.get('__tag__', k))):
                res = self._compare_result(subs, ex_obj, res_obj)
                matched_value = res or matched_value

        elif isinstance(expected, basestring) and '%' in expected:
            # NOTE(vish): escape stuff for regex
            for char in '[]<>?':
                expected = expected.replace(char, '\\%s' % char)
            expected = expected % subs
            match = re.match(expected, result)
            if not match:
                raise NoMatch(_('Values do not match:\n'
                        '%(expected)s\n%(result)s') % locals())
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
            'password': '[0-9a-zA-Z]{1,12}',
            'ip': '[0-9]{1,3}.[0-9]{1,3}.[0-9]{1,3}.[0-9]{1,3}',
            'ip6': '([0-9a-zA-Z]{1,4}:){1,7}:?[0-9a-zA-Z]',
            'id': '([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}'
                  '-[0-9a-f]{4}-[0-9a-f]{12})',
            'uuid': '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}'
                    '-[0-9a-f]{4}-[0-9a-f]{12}',
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

    def _do_delete(self, url):
        return self._get_response(url, 'DELETE')


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
        return self._verify_response('servers-details-resp', subs, response)


class ServersSampleXmlTest(ServersSampleJsonTest):
    ctype = 'xml'


class ServersSampleAllExtensionJsonTest(ServersSampleJsonTest):
    all_extensions = True


class ServersSampleAllExtensionXmlTest(ServersSampleXmlTest):
    all_extensions = True


class ServersMetadataJsonTest(ServersSampleBase):
    def _create_and_set(self, subs):
        uuid = self._post_server()
        response = self._do_put('servers/%s/metadata' % uuid,
                                'server-metadata-all-req',
                                subs)
        self.assertEqual(response.status, 200)
        self._verify_response('server-metadata-all-resp', subs, response)

        return uuid

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


class ServersActionsJsonTest(ServersSampleBase):
    def setUp(self):
        super(ServersActionsJsonTest, self).setUp()

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
        FLAGS.allow_resize_to_same_host = True
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
        f['osapi_compute_extension'] = FLAGS.osapi_compute_extension[:]
        # Flavorextradata extension also needs Flavormanage to be loaded.
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.flavormanage.Flavormanage')
        return f

    def test_flavors_extra_data_get(self):
        response = self._do_get('flavors/1')
        subs = self._get_regexes()
        return self._verify_response('flavors-extra-data-get-resp', subs,
                                     response)

    def test_flavors_extra_data_list(self):
        response = self._do_get('flavors/detail')
        subs = self._get_regexes()
        return self._verify_response('flavors-extra-data-list-resp', subs,
                                     response)

    def test_flavors_extra_data_post(self):
        response = self._do_post('flavors',
                                 'flavors-extra-data-post-req',
                                 {})
        self.assertEqual(response.status, 200)
        subs = self._get_regexes()
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
                 'image_near': str(uuid.uuid4())
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
        return self._verify_response('extended-server-attrs-get',
                                     subs, response)

    def test_extended_server_attrs_list(self):
        uuid = self._post_server()

        response = self._do_get('servers/detail')
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['instance_name'] = 'instance-\d{8}'
        return self._verify_response('extended-server-attrs-list',
                                     subs, response)


class ExtendedServerAttributesXmlTest(ExtendedServerAttributesJsonTest):
    ctype = 'xml'


class FloatingIpsJsonTest(ApiSampleTestBase):
    extension_name = "nova.api.openstack.compute.contrib." \
        "floating_ips.Floating_ips"

    def setUp(self):
        super(FloatingIpsJsonTest, self).setUp()
        pool = FLAGS.default_floating_pool
        interface = FLAGS.public_interface

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
                                 {"pool": FLAGS.default_floating_pool})
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


class KeyPairsSampleJsonTest(ApiSampleTestBase):
    extension_name = "nova.api.openstack.compute.contrib.keypairs.Keypairs"

    def test_keypairs_post(self, public_key=None):
        """Get api sample of key pairs post request"""
        key_name = 'keypair-' + str(uuid.uuid4())
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
        key_name = 'keypair-' + str(uuid.uuid4())
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
