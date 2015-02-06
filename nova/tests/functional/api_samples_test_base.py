# Copyright 2012 Nebula, Inc.
# Copyright 2013 IBM Corp.
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

from oslo_serialization import jsonutils
from oslo_utils import importutils
import six

from nova import test
from nova.tests.functional import integrated_helpers


class NoMatch(test.TestingException):
    pass


class ApiSampleTestBase(integrated_helpers._IntegratedTestBase):
    ctype = 'json'
    all_extensions = False
    extension_name = None

    def _pretty_data(self, data):
        data = jsonutils.dumps(jsonutils.loads(data), sort_keys=True,
                indent=4)
        return '\n'.join(line.rstrip() for line in data.split('\n')).strip()

    def _objectify(self, data):
        if not data:
            return {}
        # NOTE(vish): allow non-quoted replacements to survive json
        data = re.sub(r'([^"])%\((.+)\)s([^"])', r'\1"%(int:\2)s"\3', data)
        return jsonutils.loads(data)

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
        dirname = os.path.normpath(os.path.join(dirname, "../../../doc"))
        return cls._get_sample_path(name, dirname)

    @classmethod
    def _get_template(cls, name):
        dirname = os.path.dirname(os.path.abspath(__file__))
        return cls._get_sample_path(name, dirname, suffix='.tpl')

    def _read_template(self, name):
        template = self._get_template(name)
        with open(template) as inf:
            return inf.read().strip()

    def _write_template(self, name, data):
        with open(self._get_template(name), 'w') as outf:
            outf.write(data)

    def _write_sample(self, name, data):
        with open(self._get_sample(name), 'w') as outf:
            outf.write(data)

    def _compare_result(self, subs, expected, result, result_str):
        matched_value = None
        if isinstance(expected, dict):
            if not isinstance(result, dict):
                raise NoMatch('%(result_str)s: %(result)s is not a dict.'
                        % {'result_str': result_str, 'result': result})
            ex_keys = sorted(expected.keys())
            res_keys = sorted(result.keys())
            if ex_keys != res_keys:
                ex_delta = []
                res_delta = []
                for key in ex_keys:
                    if key not in res_keys:
                        ex_delta.append(key)
                for key in res_keys:
                    if key not in ex_keys:
                        res_delta.append(key)
                raise NoMatch(
                        'Dictionary key mismatch:\n'
                        'Extra key(s) in template:\n%(ex_delta)s\n'
                        'Extra key(s) in %(result_str)s:\n%(res_delta)s\n' %
                        {'ex_delta': ex_delta, 'result_str': result_str,
                           'res_delta': res_delta})
            for key in ex_keys:
                res = self._compare_result(subs, expected[key], result[key],
                                           result_str)
                matched_value = res or matched_value
        elif isinstance(expected, list):
            if not isinstance(result, list):
                raise NoMatch(
                        '%(result_str)s: %(result)s is not a list.' %
                        {'result_str': result_str, 'result': result})

            expected = expected[:]
            extra = []
            for res_obj in result:
                for i, ex_obj in enumerate(expected):
                    try:
                        matched_value = self._compare_result(subs, ex_obj,
                                                             res_obj,
                                                             result_str)
                        del expected[i]
                        break
                    except NoMatch:
                        pass
                else:
                    extra.append(res_obj)

            error = []
            if expected:
                error.append('Extra list items in template:')
                error.extend([repr(o) for o in expected])

            if extra:
                error.append('Extra list items in %(result_str)s:' %
                             {'result_str': result_str})
                error.extend([repr(o) for o in extra])

            if error:
                raise NoMatch('\n'.join(error))
        elif isinstance(expected, six.string_types) and '%' in expected:
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
                raise NoMatch(
                    'Values do not match:\n'
                    'Template: %(expected)s\n%(result_str)s: %(result)s' %
                    {'expected': expected, 'result_str': result_str,
                        'result': result})
            try:
                matched_value = match.group('id')
            except IndexError:
                if match.groups():
                    matched_value = match.groups()[0]
        else:
            if isinstance(expected, six.string_types):
                # NOTE(danms): Ignore whitespace in this comparison
                expected = expected.strip()
                if isinstance(result, six.string_types):
                    result = result.strip()
            if expected != result:
                raise NoMatch(
                        'Values do not match:\n'
                        'Template: %(expected)s\n%(result_str)s: '
                        '%(result)s' % {'expected': expected,
                                        'result_str': result_str,
                                        'result': result})
        return matched_value

    def generalize_subs(self, subs, vanilla_regexes):
        """Give the test a chance to modify subs after the server response
        was verified, and before the on-disk doc/api_samples file is checked.
        This may be needed by some tests to convert exact matches expected
        from the server into pattern matches to verify what is in the
        sample file.

        If there are no changes to be made, subs is returned unharmed.
        """
        return subs

    def _verify_response(self, name, subs, response, exp_code):
        self.assertEqual(response.status_code, exp_code)
        response_data = response.content
        response_data = self._pretty_data(response_data)
        if not os.path.exists(self._get_template(name)):
            self._write_template(name, response_data)
            template_data = response_data
        else:
            template_data = self._read_template(name)

        if (self.generate_samples and
                not os.path.exists(self._get_sample(name))):
            self._write_sample(name, response_data)
            sample_data = response_data
        else:
            with file(self._get_sample(name)) as sample:
                sample_data = sample.read()

        try:
            template_data = self._objectify(template_data)
            response_data = self._objectify(response_data)
            response_result = self._compare_result(subs, template_data,
                                                   response_data, "Response")
            # NOTE(danms): replace some of the subs with patterns for the
            # doc/api_samples check, which won't have things like the
            # correct compute host name. Also let the test do some of its
            # own generalization, if necessary
            vanilla_regexes = self._get_regexes()
            subs['compute_host'] = vanilla_regexes['host_name']
            subs['id'] = vanilla_regexes['id']
            subs = self.generalize_subs(subs, vanilla_regexes)
            sample_data = self._objectify(sample_data)
            self._compare_result(subs, template_data, sample_data, "Sample")
            return response_result
        except NoMatch:
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
        isotime_re = '\d{4}-[0,1]\d-[0-3]\dT\d{2}:\d{2}:\d{2}Z'
        strtime_re = '\d{4}-[0,1]\d-[0-3]\dT\d{2}:\d{2}:\d{2}\.\d{6}'
        xmltime_re = ('\d{4}-[0,1]\d-[0-3]\d '
                      '\d{2}:\d{2}:\d{2}'
                      '(\.\d{6})?(\+00:00)?')
        return {
            'isotime': isotime_re,
            'strtime': strtime_re,
            'strtime_or_none': r'None|%s' % strtime_re,
            'xmltime': xmltime_re,
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
                          'Generated-by-Nova',
            'fingerprint': '([0-9a-f]{2}:){15}[0-9a-f]{2}',
            'host': self._get_host(),
            'host_name': '[0-9a-z]{32}',
            'glance_host': self._get_glance_host(),
            'compute_host': self.compute.host,
            'text': text,
            'int': '[0-9]+',
        }

    def _get_response(self, url, method, body=None, strip_version=False,
                      api_version=None):
        headers = {}
        headers['Content-Type'] = 'application/' + self.ctype
        headers['Accept'] = 'application/' + self.ctype
        if api_version:
            headers['X-OpenStack-Compute-API-Version'] = api_version
        return self.api.api_request(url, body=body, method=method,
                headers=headers, strip_version=strip_version)

    def _do_get(self, url, strip_version=False, api_version=None):
        return self._get_response(url, 'GET', strip_version=strip_version,
                                  api_version=api_version)

    def _do_post(self, url, name, subs, method='POST', api_version=None):
        body = self._read_template(name) % subs
        sample = self._get_sample(name)
        if self.generate_samples and not os.path.exists(sample):
                self._write_sample(name, body)
        return self._get_response(url, method, body, api_version=api_version)

    def _do_put(self, url, name, subs, api_version=None):
        return self._do_post(url, name, subs, method='PUT',
                             api_version=api_version)

    def _do_delete(self, url, api_version=None):
        return self._get_response(url, 'DELETE', api_version=api_version)
