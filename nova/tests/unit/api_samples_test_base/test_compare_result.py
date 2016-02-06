# Copyright 2015 HPE, Inc.
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

import mock
import testtools

from nova import test
from nova.tests.functional import api_samples_test_base


class TestCompareResult(test.NoDBTestCase):
    """Provide test coverage for result comparison logic in functional tests.

        _compare_result two types of comparisons, template data and sample
        data.

        Template data means the response is checked against a regex that is
        referenced by the template name. The template name is specified in
        the format %(name)

        Sample data is a normal value comparison.
    """

    def getApiSampleTestBaseHelper(self):
        """Build an instance without running any unwanted test methods"""

        # NOTE(auggy): TestCase takes a "test" method name to run in __init__
        # calling this way prevents additional test methods from running
        ast_instance = api_samples_test_base.ApiSampleTestBase('setUp')

        # required by ApiSampleTestBase
        ast_instance.api_major_version = 'v2'
        ast_instance._project_id = 'True'

        # automagically create magic methods usually handled by test classes
        ast_instance.compute = mock.MagicMock()

        return ast_instance

    def setUp(self):
        super(TestCompareResult, self).setUp()
        self.ast = self.getApiSampleTestBaseHelper()

    def test_bare_strings_match(self):
        """compare 2 bare strings that match"""
        sample_data = u'foo'
        response_data = u'foo'
        result = self.ast._compare_result(
                subs=self.ast._get_regexes(),
                expected=sample_data,
                result=response_data,
                result_str="Test")

        # NOTE(auggy): _compare_result will not return a matched value in the
        # case of bare strings. If they don't match it will throw an exception,
        # otherwise it returns "None".
        self.assertEqual(
                expected=None,
                observed=result,
                message='Check _compare_result of 2 bare strings')

    def test_bare_strings_no_match(self):
        """check 2 bare strings that don't match"""
        sample_data = u'foo'
        response_data = u'bar'

        with testtools.ExpectedException(api_samples_test_base.NoMatch):
            self.ast._compare_result(
                    subs=self.ast._get_regexes(),
                    expected=sample_data,
                    result=response_data,
                    result_str="Test")

    def test_template_strings_match(self):
        """compare 2 template strings (contain %) that match"""
        template_data = u'%(id)s'
        response_data = u'858f295a-8543-45fa-804a-08f8356d616d'
        result = self.ast._compare_result(
                subs=self.ast._get_regexes(),
                expected=template_data,
                result=response_data,
                result_str="Test")

        self.assertEqual(
                expected=response_data,
                observed=result,
                message='Check _compare_result of 2 template strings')

    def test_template_strings_no_match(self):
        """check 2 template strings (contain %) that don't match"""
        template_data = u'%(id)s'
        response_data = u'$58f295a-8543-45fa-804a-08f8356d616d'

        with testtools.ExpectedException(api_samples_test_base.NoMatch):
            self.ast._compare_result(
                    subs=self.ast._get_regexes(),
                    expected=template_data,
                    result=response_data,
                    result_str="Test")

    # TODO(auggy): _compare_result needs a consistent return value
    # In some cases it returns the value if it matched, in others it returns
    # None. In all cases, it throws an exception if there's no match.
    def test_bare_int_match(self):
        """check 2 bare ints that match"""
        sample_data = 42
        response_data = 42
        result = self.ast._compare_result(
                subs=self.ast._get_regexes(),
                expected=sample_data,
                result=response_data,
                result_str="Test")
        self.assertEqual(
                expected=None,
                observed=result,
                message='Check _compare_result of 2 bare ints')

    # TODO(auggy): _compare_result should throw NoMatch for ints
    # this gets to objectify() and it throws a TypeError
    # versions are a case where ints are compared,
    # currently if the version in the json sample doesn't match what's in the
    # template, this throws a confusing "TypeError"
    def test_bare_int_no_match(self):
        """check 2 bare ints that don't match"""
        sample_data = 42
        response_data = 43

        with testtools.ExpectedException(TypeError):
            self.ast._compare_result(
                    subs=self.ast._get_regexes(),
                    expected=sample_data,
                    result=response_data,
                    result_str="Test")

    # TODO(auggy): _compare_result needs a consistent return value
    def test_template_int_match(self):
        """check template int against string containing digits"""
        template_data = u'%(int)s'
        response_data = u'42'

        result = self.ast._compare_result(
                subs=self.ast._get_regexes(),
                expected=template_data,
                result=response_data,
                result_str="Test")

        self.assertEqual(
                expected=None,
                observed=result,
                message='Check _compare_result of template ints')

    def test_template_int_no_match(self):
        """check template int against a string containing no digits"""
        template_data = u'%(int)s'
        response_data = u'foo'

        with testtools.ExpectedException(api_samples_test_base.NoMatch):
            self.ast._compare_result(
                    subs=self.ast._get_regexes(),
                    expected=template_data,
                    result=response_data,
                    result_str="Test")

    # TODO(auggy): _compare_result should throw TypeError early for non-strings
    def test_template_int_value(self):
        """check an int value of a template int throws exception"""
        template_data = u'%(int_test)'
        response_data = 42

        # use an int instead of a string as the subs value
        subs = self.ast._get_regexes()
        subs.update({'int_test': 42})

        # gets to expected = expected % subs
        # throws ValueError: incomplete format
        # If a string is required for that functionality,
        # the method should typecheck before it gets that deep in the code
        self.assertRaises(
                excClass=ValueError,  # this should be a TypeError
                callableObj=self.ast._compare_result,
                subs=subs,  # subs can be defined by the caller, needs checking
                expected=template_data,
                result=response_data,
                result_str="Test")

    # TODO(auggy): _compare_result needs a consistent return value
    def test_dict_match(self):
        """check 2 matching dictionaries"""
        template_data = {
            u'server': {
                u'id': u'%(id)s',
                u'adminPass': u'%(password)s'
            }
        }
        response_data = {
            u'server': {
                u'id': u'858f295a-8543-45fa-804a-08f8356d616d',
                u'adminPass': u'4ZQ3bb6WYbC2'}
        }

        result = self.ast._compare_result(
                subs=self.ast._get_regexes(),
                expected=template_data,
                result=response_data,
                result_str="Test")

        self.assertEqual(
                expected=u'858f295a-8543-45fa-804a-08f8356d616d',
                observed=result,
                message='Check _compare_result of 2 dictionaries')

    def test_dict_no_match_value(self):
        """check 2 dictionaries where one has a different value"""
        sample_data = {
            u'server': {
                u'id': u'858f295a-8543-45fa-804a-08f8356d616d',
                u'adminPass': u'foo'
            }
        }
        response_data = {
            u'server': {
                u'id': u'858f295a-8543-45fa-804a-08f8356d616d',
                u'adminPass': u'4ZQ3bb6WYbC2'}
        }

        with testtools.ExpectedException(api_samples_test_base.NoMatch):
            self.ast._compare_result(
                    subs=self.ast._get_regexes(),
                    expected=sample_data,
                    result=response_data,
                    result_str="Test")

    def test_dict_no_match_extra_key(self):
        """check 2 dictionaries where one has an extra key"""
        template_data = {
            u'server': {
                u'id': u'%(id)s',
                u'adminPass': u'%(password)s',
                u'foo': u'foo'
            }
        }
        response_data = {
            u'server': {
                u'id': u'858f295a-8543-45fa-804a-08f8356d616d',
                u'adminPass': u'4ZQ3bb6WYbC2'}
        }

        with testtools.ExpectedException(api_samples_test_base.NoMatch):
            self.ast._compare_result(
                    subs=self.ast._get_regexes(),
                    expected=template_data,
                    result=response_data,
                    result_str="Test")

    def test_dict_result_type_mismatch(self):
        """check expected is a dictionary and result is not a dictionary"""

        template_data = {
            u'server': {
                u'id': u'%(id)s',
                u'adminPass': u'%(password)s',
            }
        }
        response_data = u'foo'

        with testtools.ExpectedException(api_samples_test_base.NoMatch):
            self.ast._compare_result(
                subs=self.ast._get_regexes(),
                expected=template_data,
                result=response_data,
                result_str="Test")

    # TODO(auggy): _compare_result needs a consistent return value
    def test_list_match(self):
        """check 2 matching lists"""
        template_data = {
            u'links':
            [
                {
                    u'href': u'%(versioned_compute_endpoint)s/server/%(uuid)s',
                    u'rel': u'self'
                },
                {
                    u'href': u'%(compute_endpoint)s/servers/%(uuid)s',
                    u'rel': u'bookmark'
                }
            ]
        }
        response_data = {
            u'links':
            [
                {
                    u'href':
                        (u'http://openstack.example.com/v2/openstack/server/'
                            '858f295a-8543-45fa-804a-08f8356d616d'),
                    u'rel': u'self'
                },
                {
                    u'href':
                        (u'http://openstack.example.com/openstack/servers/'
                            '858f295a-8543-45fa-804a-08f8356d616d'),
                    u'rel': u'bookmark'
                }
            ]
        }

        result = self.ast._compare_result(
                subs=self.ast._get_regexes(),
                expected=template_data,
                result=response_data,
                result_str="Test")

        self.assertEqual(
                expected=None,
                observed=result,
                message='Check _compare_result of 2 lists')

    def test_list_match_extra_item_result(self):
        """check extra list items in result """
        template_data = {
            u'links':
            [
                {
                    u'href': u'%(versioned_compute_endpoint)s/server/%(uuid)s',
                    u'rel': u'self'
                },
                {
                    u'href': u'%(compute_endpoint)s/servers/%(uuid)s',
                    u'rel': u'bookmark'
                }
            ]
        }
        response_data = {
            u'links':
            [
                {
                    u'href':
                        (u'http://openstack.example.com/v2/openstack/server/'
                            '858f295a-8543-45fa-804a-08f8356d616d'),
                    u'rel': u'self'
                },
                {
                    u'href':
                        (u'http://openstack.example.com/openstack/servers/'
                            '858f295a-8543-45fa-804a-08f8356d616d'),
                    u'rel': u'bookmark'
                },
                u'foo'
            ]
        }

        with testtools.ExpectedException(api_samples_test_base.NoMatch):
            self.ast._compare_result(
                subs=self.ast._get_regexes(),
                expected=template_data,
                result=response_data,
                result_str="Test")

    def test_list_match_extra_item_template(self):
        """check extra list items in template """
        template_data = {
            u'links':
            [
                {
                    u'href': u'%(versioned_compute_endpoint)s/server/%(uuid)s',
                    u'rel': u'self'
                },
                {
                    u'href': u'%(compute_endpoint)s/servers/%(uuid)s',
                    u'rel': u'bookmark'
                },
                u'foo'  # extra field
            ]
        }
        response_data = {
            u'links':
            [
                {
                    u'href':
                        (u'http://openstack.example.com/v2/openstack/server/'
                            '858f295a-8543-45fa-804a-08f8356d616d'),
                    u'rel': u'self'
                },
                {
                    u'href':
                        (u'http://openstack.example.com/openstack/servers/'
                            '858f295a-8543-45fa-804a-08f8356d616d'),
                    u'rel': u'bookmark'
                }
            ]
        }

        with testtools.ExpectedException(api_samples_test_base.NoMatch):
            self.ast._compare_result(
                    subs=self.ast._get_regexes(),
                    expected=template_data,
                    result=response_data,
                    result_str="Test")
