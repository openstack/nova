# Copyright 2011 Andrew Bogott for the Wikimedia Foundation
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

import mock
from oslo_serialization import jsonutils
import six
import webob

from nova.api.openstack import api_version_request
from nova.api.openstack.compute import flavor_access as flavor_access_v21
from nova.api.openstack.compute import flavor_manage as flavormanage_v21
from nova.compute import flavors
from nova import db
from nova import exception
from nova import objects
from nova import policy
from nova import test
from nova.tests.unit.api.openstack import fakes


def fake_create(newflavor):
    newflavor['flavorid'] = 1234
    newflavor["name"] = 'test'
    newflavor["memory_mb"] = 512
    newflavor["vcpus"] = 2
    newflavor["root_gb"] = 1
    newflavor["ephemeral_gb"] = 1
    newflavor["swap"] = 512
    newflavor["rxtx_factor"] = 1.0
    newflavor["is_public"] = True
    newflavor["disabled"] = False


class FlavorManageTestV21(test.NoDBTestCase):
    controller = flavormanage_v21.FlavorManageController()
    validation_error = exception.ValidationError
    base_url = '/v2/fake/flavors'
    microversion = '2.1'

    def setUp(self):
        super(FlavorManageTestV21, self).setUp()
        self.stub_out("nova.objects.Flavor.create", fake_create)

        self.request_body = {
            "flavor": {
                "name": "test",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
                "OS-FLV-EXT-DATA:ephemeral": 1,
                "id": six.text_type('1234'),
                "swap": 512,
                "rxtx_factor": 1,
                "os-flavor-access:is_public": True,
            }
        }
        self.expected_flavor = self.request_body

    def _get_http_request(self, url=''):
        return fakes.HTTPRequest.blank(url, version=self.microversion,
                                       use_admin_context=True)

    @property
    def app(self):
        return fakes.wsgi_app_v21()

    @mock.patch('nova.objects.Flavor.destroy')
    def test_delete(self, mock_destroy):
        res = self.controller._delete(self._get_http_request(), 1234)

        # NOTE: on v2.1, http status code is set as wsgi_code of API
        # method instead of status_int in a response object.
        if isinstance(self.controller,
                      flavormanage_v21.FlavorManageController):
            status_int = self.controller._delete.wsgi_code
        else:
            status_int = res.status_int
        self.assertEqual(202, status_int)

        # subsequent delete should fail
        mock_destroy.side_effect = exception.FlavorNotFound(flavor_id=1234)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller._delete, self._get_http_request(),
                          1234)

    def _test_create_missing_parameter(self, parameter):
        body = {
            "flavor": {
                "name": "azAZ09. -_",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
                "OS-FLV-EXT-DATA:ephemeral": 1,
                "id": six.text_type('1234'),
                "swap": 512,
                "rxtx_factor": 1,
                "os-flavor-access:is_public": True,
            }
        }

        del body['flavor'][parameter]

        self.assertRaises(self.validation_error, self.controller._create,
                          self._get_http_request(), body=body)

    def test_create_missing_name(self):
        self._test_create_missing_parameter('name')

    def test_create_missing_ram(self):
        self._test_create_missing_parameter('ram')

    def test_create_missing_vcpus(self):
        self._test_create_missing_parameter('vcpus')

    def test_create_missing_disk(self):
        self._test_create_missing_parameter('disk')

    def _create_flavor_success_case(self, body, req=None):
        req = req if req else self._get_http_request(url=self.base_url)
        req.headers['Content-Type'] = 'application/json'
        req.headers['X-OpenStack-Nova-API-Version'] = self.microversion
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes(body)
        res = req.get_response(self.app)
        self.assertEqual(200, res.status_code)
        return jsonutils.loads(res.body)

    def test_create(self):
        body = self._create_flavor_success_case(self.request_body)
        for key in self.expected_flavor["flavor"]:
            self.assertEqual(body["flavor"][key],
                             self.expected_flavor["flavor"][key])

    def test_create_public_default(self):
        del self.request_body['flavor']['os-flavor-access:is_public']
        body = self._create_flavor_success_case(self.request_body)
        for key in self.expected_flavor["flavor"]:
            self.assertEqual(body["flavor"][key],
                             self.expected_flavor["flavor"][key])

    def test_create_without_flavorid(self):
        del self.request_body['flavor']['id']
        body = self._create_flavor_success_case(self.request_body)
        for key in self.expected_flavor["flavor"]:
            self.assertEqual(body["flavor"][key],
                             self.expected_flavor["flavor"][key])

    def _create_flavor_bad_request_case(self, body):
        self.assertRaises(self.validation_error, self.controller._create,
                          self._get_http_request(), body=body)

    def test_create_invalid_name(self):
        self.request_body['flavor']['name'] = 'bad !@#!$%\x00 name'
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_flavor_name_is_whitespace(self):
        self.request_body['flavor']['name'] = ' '
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_name_too_long(self):
        self.request_body['flavor']['name'] = 'a' * 256
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_name_leading_trailing_spaces(self):
        self.request_body['flavor']['name'] = '  test  '
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_name_leading_trailing_spaces_compat_mode(self):
        req = self._get_http_request(url=self.base_url)
        req.set_legacy_v2()
        self.request_body['flavor']['name'] = '  test  '
        body = self._create_flavor_success_case(self.request_body, req)
        self.assertEqual('test', body['flavor']['name'])

    def test_create_without_flavorname(self):
        del self.request_body['flavor']['name']
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_empty_body(self):
        body = {
            "flavor": {}
        }
        self._create_flavor_bad_request_case(body)

    def test_create_no_body(self):
        body = {}
        self._create_flavor_bad_request_case(body)

    def test_create_invalid_format_body(self):
        body = {
            "flavor": []
        }
        self._create_flavor_bad_request_case(body)

    def test_create_invalid_flavorid(self):
        self.request_body['flavor']['id'] = "!@#!$#!$^#&^$&"
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_check_flavor_id_length(self):
        MAX_LENGTH = 255
        self.request_body['flavor']['id'] = "a" * (MAX_LENGTH + 1)
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_leading_trailing_whitespaces_in_flavor_id(self):
        self.request_body['flavor']['id'] = "   bad_id   "
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_without_ram(self):
        del self.request_body['flavor']['ram']
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_0_ram(self):
        self.request_body['flavor']['ram'] = 0
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_ram_exceed_max_limit(self):
        self.request_body['flavor']['ram'] = db.MAX_INT + 1
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_without_vcpus(self):
        del self.request_body['flavor']['vcpus']
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_0_vcpus(self):
        self.request_body['flavor']['vcpus'] = 0
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_vcpus_exceed_max_limit(self):
        self.request_body['flavor']['vcpus'] = db.MAX_INT + 1
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_without_disk(self):
        del self.request_body['flavor']['disk']
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_minus_disk(self):
        self.request_body['flavor']['disk'] = -1
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_disk_exceed_max_limit(self):
        self.request_body['flavor']['disk'] = db.MAX_INT + 1
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_minus_ephemeral(self):
        self.request_body['flavor']['OS-FLV-EXT-DATA:ephemeral'] = -1
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_ephemeral_exceed_max_limit(self):
        self.request_body['flavor'][
            'OS-FLV-EXT-DATA:ephemeral'] = db.MAX_INT + 1
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_minus_swap(self):
        self.request_body['flavor']['swap'] = -1
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_swap_exceed_max_limit(self):
        self.request_body['flavor']['swap'] = db.MAX_INT + 1
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_minus_rxtx_factor(self):
        self.request_body['flavor']['rxtx_factor'] = -1
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_rxtx_factor_exceed_max_limit(self):
        self.request_body['flavor']['rxtx_factor'] = db.SQL_SP_FLOAT_MAX * 2
        self._create_flavor_bad_request_case(self.request_body)

    def test_create_with_non_boolean_is_public(self):
        self.request_body['flavor']['os-flavor-access:is_public'] = 123
        self._create_flavor_bad_request_case(self.request_body)

    def test_flavor_exists_exception_returns_409(self):
        expected = {
            "flavor": {
                "name": "test",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
                "OS-FLV-EXT-DATA:ephemeral": 1,
                "id": 1235,
                "swap": 512,
                "rxtx_factor": 1,
                "os-flavor-access:is_public": True,
            }
        }

        def fake_create(name, memory_mb, vcpus, root_gb, ephemeral_gb,
                        flavorid, swap, rxtx_factor, is_public, description):
            raise exception.FlavorExists(name=name)

        self.stub_out('nova.compute.flavors.create', fake_create)
        self.assertRaises(webob.exc.HTTPConflict, self.controller._create,
                          self._get_http_request(), body=expected)

    def test_invalid_memory_mb(self):
        """Check negative and decimal number can't be accepted."""
        self.assertRaises(exception.InvalidInput, flavors.create, "abc",
                          -512, 2, 1, 1, 1234, 512, 1, True)
        self.assertRaises(exception.InvalidInput, flavors.create, "abcd",
                          512.2, 2, 1, 1, 1234, 512, 1, True)
        self.assertRaises(exception.InvalidInput, flavors.create, "abcde",
                          None, 2, 1, 1, 1234, 512, 1, True)
        self.assertRaises(exception.InvalidInput, flavors.create, "abcdef",
                          512, 2, None, 1, 1234, 512, 1, True)
        self.assertRaises(exception.InvalidInput, flavors.create, "abcdef",
                          "test_memory_mb", 2, None, 1, 1234, 512, 1, True)

    def test_create_with_description(self):
        """With microversion <2.55 this should return a failure."""
        self.request_body['flavor']['description'] = 'invalid'
        ex = self.assertRaises(
            self.validation_error, self.controller._create,
            self._get_http_request(), body=self.request_body)
        self.assertIn('description', six.text_type(ex))

    def test_flavor_update_description(self):
        """With microversion <2.55 this should return a failure."""
        flavor = self._create_flavor_success_case(self.request_body)['flavor']
        self.assertRaises(
            exception.VersionNotFoundForAPIMethod, self.controller._update,
            self._get_http_request(), flavor['id'],
            body={'flavor': {'description': 'nope'}})


class FlavorManageTestV2_55(FlavorManageTestV21):
    microversion = '2.55'

    def setUp(self):
        super(FlavorManageTestV2_55, self).setUp()
        # Send a description in POST /flavors requests.
        self.request_body['flavor']['description'] = 'test description'

    def test_create_with_description(self):
        # test_create already tests this.
        pass

    @mock.patch('nova.objects.Flavor.get_by_flavor_id')
    @mock.patch('nova.objects.Flavor.save')
    def test_flavor_update_description(self, mock_flavor_save, mock_get):
        """Tests updating a flavor description."""
        # First create a flavor.
        flavor = self._create_flavor_success_case(self.request_body)['flavor']
        self.assertEqual('test description', flavor['description'])
        mock_get.return_value = objects.Flavor(
            flavorid=flavor['id'], name=flavor['name'],
            memory_mb=flavor['ram'], vcpus=flavor['vcpus'],
            root_gb=flavor['disk'], swap=flavor['swap'],
            ephemeral_gb=flavor['OS-FLV-EXT-DATA:ephemeral'],
            disabled=flavor['OS-FLV-DISABLED:disabled'],
            is_public=flavor['os-flavor-access:is_public'],
            rxtx_factor=flavor['rxtx_factor'],
            description=flavor['description'])
        # Now null out the flavor description.
        flavor = self.controller._update(
            self._get_http_request(), flavor['id'],
            body={'flavor': {'description': None}})['flavor']
        self.assertIsNone(flavor['description'])
        mock_get.assert_called_once_with(
            test.MatchType(fakes.FakeRequestContext), flavor['id'])
        mock_flavor_save.assert_called_once_with()

    @mock.patch('nova.objects.Flavor.get_by_flavor_id',
                side_effect=exception.FlavorNotFound(flavor_id='notfound'))
    def test_flavor_update_not_found(self, mock_get):
        """Tests that a 404 is returned if the flavor is not found."""
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller._update,
                          self._get_http_request(), 'notfound',
                          body={'flavor': {'description': None}})

    def test_flavor_update_missing_description(self):
        """Tests that a schema validation error is raised if no description
        is provided in the update request body.
        """
        self.assertRaises(self.validation_error,
                          self.controller._update,
                          self._get_http_request(), 'invalid',
                          body={'flavor': {}})

    def test_create_with_invalid_description(self):
        # NOTE(mriedem): Intentionally not using ddt for this since ddt will
        # create a test name that has 65536 'a's in the name which blows up
        # the console output.
        for description in ('bad !@#!$%\x00 description',   # printable chars
                            'a' * 65536):                   # maxLength
            self.request_body['flavor']['description'] = description
            self.assertRaises(self.validation_error, self.controller._create,
                              self._get_http_request(), body=self.request_body)

    @mock.patch('nova.objects.Flavor.get_by_flavor_id')
    @mock.patch('nova.objects.Flavor.save')
    def test_update_with_invalid_description(self, mock_flavor_save, mock_get):
        # First create a flavor.
        flavor = self._create_flavor_success_case(self.request_body)['flavor']
        self.assertEqual('test description', flavor['description'])
        mock_get.return_value = objects.Flavor(
            flavorid=flavor['id'], name=flavor['name'],
            memory_mb=flavor['ram'], vcpus=flavor['vcpus'],
            root_gb=flavor['disk'], swap=flavor['swap'],
            ephemeral_gb=flavor['OS-FLV-EXT-DATA:ephemeral'],
            disabled=flavor['OS-FLV-DISABLED:disabled'],
            is_public=flavor['os-flavor-access:is_public'],
            description=flavor['description'])
        # NOTE(mriedem): Intentionally not using ddt for this since ddt will
        # create a test name that has 65536 'a's in the name which blows up
        # the console output.
        for description in ('bad !@#!$%\x00 description',   # printable chars
                            'a' * 65536):                   # maxLength
            self.request_body['flavor']['description'] = description
            self.assertRaises(self.validation_error, self.controller._update,
                              self._get_http_request(), flavor['id'],
                              body={'flavor': {'description': description}})


class PrivateFlavorManageTestV21(test.TestCase):
    controller = flavormanage_v21.FlavorManageController()
    base_url = '/v2/fake/flavors'

    def setUp(self):
        super(PrivateFlavorManageTestV21, self).setUp()
        self.flavor_access_controller = (flavor_access_v21.
                                         FlavorAccessController())
        self.expected = {
            "flavor": {
                "name": "test",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
                "OS-FLV-EXT-DATA:ephemeral": 1,
                "swap": 512,
                "rxtx_factor": 1
            }
        }

    @property
    def app(self):
        return fakes.wsgi_app_v21(fake_auth_context=self._get_http_request().
                                     environ['nova.context'])

    def _get_http_request(self, url=''):
        return fakes.HTTPRequest.blank(url)

    def _get_response(self):
        req = self._get_http_request(self.base_url)
        req.headers['Content-Type'] = 'application/json'
        req.method = 'POST'
        req.body = jsonutils.dump_as_bytes(self.expected)
        res = req.get_response(self.app)
        return jsonutils.loads(res.body)

    def test_create_private_flavor_should_not_grant_flavor_access(self):
        self.expected["flavor"]["os-flavor-access:is_public"] = False
        body = self._get_response()
        for key in self.expected["flavor"]:
            self.assertEqual(body["flavor"][key], self.expected["flavor"][key])
        # Because for normal user can't access the non-public flavor without
        # access. So it need admin context at here.
        flavor_access_body = self.flavor_access_controller.index(
            fakes.HTTPRequest.blank('', use_admin_context=True),
            body["flavor"]["id"])
        expected_flavor_access_body = {
            "tenant_id": 'fake',
            "flavor_id": "%s" % body["flavor"]["id"]
        }
        self.assertNotIn(expected_flavor_access_body,
                         flavor_access_body["flavor_access"])

    def test_create_public_flavor_should_not_create_flavor_access(self):
        self.expected["flavor"]["os-flavor-access:is_public"] = True
        body = self._get_response()
        for key in self.expected["flavor"]:
            self.assertEqual(body["flavor"][key], self.expected["flavor"][key])


class FlavorManagerPolicyEnforcementV21(test.TestCase):

    def setUp(self):
        super(FlavorManagerPolicyEnforcementV21, self).setUp()
        self.controller = flavormanage_v21.FlavorManageController()
        self.adm_req = fakes.HTTPRequest.blank('', use_admin_context=True)
        self.req = fakes.HTTPRequest.blank('')

    def test_create_policy_failed(self):
        rule_name = "os_compute_api:os-flavor-manage"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._create, self.req,
            body={"flavor": {
                "name": "test",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
                "swap": 512,
                "rxtx_factor": 1,
            }})
        # The deprecated action is being enforced since the rule that is
        # configured is different than the default rule
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    def test_delete_policy_failed(self):
        rule_name = "os_compute_api:os-flavor-manage"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._delete, self.req,
            fakes.FAKE_UUID)
        # The deprecated action is being enforced since the rule that is
        # configured is different than the default rule
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())

    @mock.patch.object(policy.LOG, 'warning')
    def test_create_policy_rbac_inherit_default(self, mock_warning):
        """Test to verify inherited rule is working. The rule of the
           deprecated action is not set to the default, so the deprecated
           action is being enforced
        """

        default_flavor_policy = "os_compute_api:os-flavor-manage"
        create_flavor_policy = "os_compute_api:os-flavor-manage:create"
        rules = {default_flavor_policy: 'is_admin:True',
                 create_flavor_policy: 'rule:%s' % default_flavor_policy,
                 "os_compute_api:os-flavor-access": "project:non_fake"}
        self.policy.set_rules(rules)
        body = {
            "flavor": {
                "name": "azAZ09. -_",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
                "OS-FLV-EXT-DATA:ephemeral": 1,
                "id": six.text_type('1234'),
                "swap": 512,
                "rxtx_factor": 1,
                "os-flavor-access:is_public": True,
            }
        }
        # check for success as admin
        self.controller._create(self.adm_req, body=body)
        # check for failure as non-admin
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller._create, self.req,
                                body=body)
        # The deprecated action is being enforced since the rule that is
        # configured is different than the default rule
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % default_flavor_policy,
            exc.format_message())
        mock_warning.assert_called_with("Start using the new "
            "action '{0}'. The existing action '{1}' is being deprecated and "
            "will be removed in future release.".format(create_flavor_policy,
                                                        default_flavor_policy))

    @mock.patch.object(policy.LOG, 'warning')
    def test_delete_policy_rbac_inherit_default(self, mock_warning):
        """Test to verify inherited rule is working. The rule of the
           deprecated action is not set to the default, so the deprecated
           action is being enforced
        """

        default_flavor_policy = "os_compute_api:os-flavor-manage"
        create_flavor_policy = "os_compute_api:os-flavor-manage:create"
        delete_flavor_policy = "os_compute_api:os-flavor-manage:delete"
        rules = {default_flavor_policy: 'is_admin:True',
                 create_flavor_policy: 'rule:%s' % default_flavor_policy,
                 delete_flavor_policy: 'rule:%s' % default_flavor_policy}
        self.policy.set_rules(rules)
        body = {
            "flavor": {
                "name": "azAZ09. -_",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
                "OS-FLV-EXT-DATA:ephemeral": 1,
                "id": six.text_type('1234'),
                "swap": 512,
                "rxtx_factor": 1,
                "os-flavor-access:is_public": True,
            }
        }
        self.flavor = self.controller._create(self.adm_req, body=body)
        mock_warning.assert_called_once_with("Start using the new "
            "action '{0}'. The existing action '{1}' is being deprecated and "
            "will be removed in future release.".format(create_flavor_policy,
                                                        default_flavor_policy))
        # check for success as admin
        flavor = self.flavor
        self.controller._delete(self.adm_req, flavor['flavor']['id'])
        # check for failure as non-admin
        flavor = self.flavor
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller._delete, self.req,
                                flavor['flavor']['id'])
        # The deprecated action is being enforced since the rule that is
        # configured is different than the default rule
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % default_flavor_policy,
            exc.format_message())
        mock_warning.assert_called_with("Start using the new "
            "action '{0}'. The existing action '{1}' is being deprecated and "
            "will be removed in future release.".format(delete_flavor_policy,
                                                        default_flavor_policy))

    def test_create_policy_rbac_no_change_to_default_action_rule(self):
        """Test to verify the correct action is being enforced. When the
           rule configured for the deprecated action is the same as the
           default, the new action should be enforced.
        """

        default_flavor_policy = "os_compute_api:os-flavor-manage"
        create_flavor_policy = "os_compute_api:os-flavor-manage:create"
        # The default rule of the deprecated action is admin_api
        rules = {default_flavor_policy: 'rule:admin_api',
                 create_flavor_policy: 'rule:%s' % default_flavor_policy}
        self.policy.set_rules(rules)
        body = {
            "flavor": {
                "name": "azAZ09. -_",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
                "OS-FLV-EXT-DATA:ephemeral": 1,
                "id": six.text_type('1234'),
                "swap": 512,
                "rxtx_factor": 1,
                "os-flavor-access:is_public": True,
            }
        }
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller._create, self.req,
                                body=body)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % create_flavor_policy,
            exc.format_message())

    def test_delete_policy_rbac_change_to_default_action_rule(self):
        """Test to verify the correct action is being enforced. When the
           rule configured for the deprecated action is the same as the
           default, the new action should be enforced.
        """

        default_flavor_policy = "os_compute_api:os-flavor-manage"
        create_flavor_policy = "os_compute_api:os-flavor-manage:create"
        delete_flavor_policy = "os_compute_api:os-flavor-manage:delete"
        # The default rule of the deprecated action is admin_api
        # Set the rule of the create flavor action to is_admin:True so that
        # admin context can be used to create a flavor
        rules = {default_flavor_policy: 'rule:admin_api',
                 create_flavor_policy: 'is_admin:True',
                 delete_flavor_policy: 'rule:%s' % default_flavor_policy}
        self.policy.set_rules(rules)
        body = {
            "flavor": {
                "name": "azAZ09. -_",
                "ram": 512,
                "vcpus": 2,
                "disk": 1,
                "OS-FLV-EXT-DATA:ephemeral": 1,
                "id": six.text_type('1234'),
                "swap": 512,
                "rxtx_factor": 1,
                "os-flavor-access:is_public": True,
            }
        }
        flavor = self.controller._create(self.adm_req, body=body)
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller._delete, self.req,
                                flavor['flavor']['id'])
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % delete_flavor_policy,
            exc.format_message())

    def test_flavor_update_non_admin_fails(self):
        """Tests that trying to update a flavor as a non-admin fails due
        to the default policy.
        """
        self.req.api_version_request = api_version_request.APIVersionRequest(
            '2.55')
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller._update, self.req, 'fake_id',
            body={"flavor": {"description": "not authorized"}})
        self.assertEqual(
            "Policy doesn't allow os_compute_api:os-flavor-manage:update to "
            "be performed.", exc.format_message())
