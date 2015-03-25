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


import inspect
import os
import re
import uuid as uuid_lib

import mock
from oslo_config import cfg
from oslo_log import log as logging
from oslo_serialization import jsonutils
from oslo_utils import importutils
import testtools

from nova.api.metadata import password
from nova.api.openstack.compute import extensions
from nova.cells import utils as cells_utils
# Import extensions to pull in osapi_compute_extension CONF option used below.
from nova.compute import api as compute_api
from nova.compute import cells_api as cells_api
from nova.console import manager as console_manager  # noqa - only for cfg
from nova.network.neutronv2 import api as neutron_api  # noqa - only for cfg
from nova import objects
from nova.servicegroup import api as service_group_api
from nova import test
from nova.tests.functional import api_samples_test_base
from nova.tests.functional import integrated_helpers
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit import fake_network
from nova.tests.unit import fake_utils
from nova.tests.unit.image import fake
from nova.volume import cinder

CONF = cfg.CONF
CONF.import_opt('allow_resize_to_same_host', 'nova.compute.api')
CONF.import_opt('shelved_offload_time', 'nova.compute.manager')
CONF.import_opt('enable_network_quota',
                'nova.api.openstack.compute.contrib.os_tenant_networks')
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.extensions')
CONF.import_opt('osapi_compute_link_prefix', 'nova.api.openstack.common')
CONF.import_opt('osapi_glance_link_prefix', 'nova.api.openstack.common')
CONF.import_opt('enable', 'nova.cells.opts', group='cells')
CONF.import_opt('cell_type', 'nova.cells.opts', group='cells')
CONF.import_opt('db_check_interval', 'nova.cells.state', group='cells')
LOG = logging.getLogger(__name__)


class ApiSampleTestBaseV2(api_samples_test_base.ApiSampleTestBase):
    _api_version = 'v2'

    def setUp(self):
        extends = []
        self.flags(use_ipv6=False,
                   osapi_compute_link_prefix=self._get_host(),
                   osapi_glance_link_prefix=self._get_glance_host())
        if not self.all_extensions:
            if hasattr(self, 'extends_name'):
                extends = [self.extends_name]
            ext = [self.extension_name] if self.extension_name else []
            self.flags(osapi_compute_extension=ext + extends)
        super(ApiSampleTestBaseV2, self).setUp()
        self.useFixture(test.SampleNetworks(host=self.network.host))
        fake_network.stub_compute_with_ips(self.stubs)
        fake_utils.stub_out_utils_spawn_n(self.stubs)
        self.generate_samples = os.getenv('GENERATE_SAMPLES') is not None


class ApiSamplesTrap(ApiSampleTestBaseV2):
    """Make sure extensions don't get added without tests."""

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
        for extension in jsonutils.loads(response.content)['extensions']:
            extensions.append(str(extension['alias']))
        return extensions

    def test_all_extensions_have_samples(self):
        # NOTE(danms): This is a list of extensions which are currently
        # in the tree but that don't (yet) have tests. This list should
        # NOT be allowed to grow, and should shrink to zero (and be
        # removed) soon.

        # TODO(gmann): skip this tests as merging of sample tests for v2
        # and v2.1 are in progress. After merging all tests, this tests
        # need to implement in different way.
        raise testtools.TestCase.skipException('Merging of v2 and v2.1 '
                                               'sample tests is in progress. '
                                               'This test will be enabled '
                                               'after all tests gets merged.')
        do_not_approve_additions = []
        do_not_approve_additions.append('os-create-server-ext')
        do_not_approve_additions.append('os-baremetal-ext-status')

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


class VersionsSampleJsonTest(ApiSampleTestBaseV2):
    sample_dir = 'versions'

    def test_versions_get(self):
        response = self._do_get('', strip_version=True)
        subs = self._get_regexes()
        self._verify_response('versions-get-resp', subs, response, 200)


class ServersSampleBase(ApiSampleTestBaseV2):
    def _post_server(self, use_common_server_api_samples=True):
        # param use_common_server_api_samples: Boolean to set whether tests use
        # common sample files for server post request and response.
        # Default is True which means _get_sample_path method will fetch the
        # common server sample files.
        # Set False if tests need to use extension specific sample files
        subs = {
            'image_id': fake.get_valid_image_id(),
            'host': self._get_host(),
        }
        orig_value = self.__class__._use_common_server_api_samples
        try:
            self.__class__._use_common_server_api_samples = (
                                        use_common_server_api_samples)
            response = self._do_post('servers', 'server-post-req', subs)
            subs = self._get_regexes()
            status = self._verify_response('server-post-resp', subs,
                                           response, 202)
            return status
        finally:
            self.__class__._use_common_server_api_samples = orig_value


class ServersSampleMultiStatusJsonTest(ServersSampleBase):
    extension_name = '.'.join(('nova.api.openstack.compute.contrib',
                               'server_list_multi_status',
                               'Server_list_multi_status'))

    def test_servers_list(self):
        uuid = self._post_server()
        response = self._do_get('servers?status=active&status=error')
        subs = self._get_regexes()
        subs['id'] = uuid
        self._verify_response('servers-list-resp', subs, response, 200)


class ExtensionsSampleJsonTest(ApiSampleTestBaseV2):
    all_extensions = True

    def test_extensions_get(self):
        response = self._do_get('extensions')
        subs = self._get_regexes()
        self._verify_response('extensions-get-resp', subs, response, 200)


class FlavorsSampleJsonTest(ApiSampleTestBaseV2):
    sample_dir = 'flavors'

    def test_flavors_get(self):
        response = self._do_get('flavors/1')
        subs = self._get_regexes()
        self._verify_response('flavor-get-resp', subs, response, 200)

    def test_flavors_list(self):
        response = self._do_get('flavors')
        subs = self._get_regexes()
        self._verify_response('flavors-list-resp', subs, response, 200)


class FlavorsSampleAllExtensionJsonTest(FlavorsSampleJsonTest):
    all_extensions = True


class LimitsSampleJsonTest(ApiSampleTestBaseV2):
    sample_dir = 'limits'

    def test_limits_get(self):
        response = self._do_get('limits')
        subs = self._get_regexes()
        self._verify_response('limit-get-resp', subs, response, 200)


class SecurityGroupsSampleJsonTest(ServersSampleBase):
    extension_name = "nova.api.openstack.compute.contrib" + \
                     ".security_groups.Security_groups"

    def _get_create_subs(self):
        return {
                'group_name': 'test',
                "description": "description",
        }

    def _create_security_group(self):
        subs = self._get_create_subs()
        return self._do_post('os-security-groups',
                             'security-group-post-req', subs)

    def _add_group(self, uuid):
        subs = {
                'group_name': 'test'
        }
        return self._do_post('servers/%s/action' % uuid,
                             'security-group-add-post-req', subs)

    def test_security_group_create(self):
        response = self._create_security_group()
        subs = self._get_create_subs()
        self._verify_response('security-groups-create-resp', subs,
                              response, 200)

    def test_security_groups_list(self):
        # Get api sample of security groups get list request.
        response = self._do_get('os-security-groups')
        subs = self._get_regexes()
        self._verify_response('security-groups-list-get-resp',
                              subs, response, 200)

    def test_security_groups_get(self):
        # Get api sample of security groups get request.
        security_group_id = '1'
        response = self._do_get('os-security-groups/%s' % security_group_id)
        subs = self._get_regexes()
        self._verify_response('security-groups-get-resp', subs, response, 200)

    def test_security_groups_list_server(self):
        # Get api sample of security groups for a specific server.
        uuid = self._post_server(use_common_server_api_samples=False)
        response = self._do_get('servers/%s/os-security-groups' % uuid)
        subs = self._get_regexes()
        self._verify_response('server-security-groups-list-resp',
                              subs, response, 200)

    def test_security_groups_add(self):
        self._create_security_group()
        uuid = self._post_server(use_common_server_api_samples=False)
        response = self._add_group(uuid)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')

    def test_security_groups_remove(self):
        self._create_security_group()
        uuid = self._post_server(use_common_server_api_samples=False)
        self._add_group(uuid)
        subs = {
                'group_name': 'test'
        }
        response = self._do_post('servers/%s/action' % uuid,
                                 'security-group-remove-post-req', subs)
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')


class SchedulerHintsJsonTest(ApiSampleTestBaseV2):
    extension_name = ("nova.api.openstack.compute.contrib.scheduler_hints."
                     "Scheduler_hints")

    def test_scheduler_hints_post(self):
        # Get api sample of scheduler hint post request.
        hints = {'image_id': fake.get_valid_image_id(),
                 'image_near': str(uuid_lib.uuid4())
        }
        response = self._do_post('servers', 'scheduler-hints-post-req',
                                 hints)
        subs = self._get_regexes()
        self._verify_response('scheduler-hints-post-resp', subs, response, 202)


class KeyPairsSampleJsonTest(ApiSampleTestBaseV2):
    extension_name = "nova.api.openstack.compute.contrib.keypairs.Keypairs"

    def generalize_subs(self, subs, vanilla_regexes):
        subs['keypair_name'] = 'keypair-[0-9a-f-]+'
        return subs

    def test_keypairs_post(self, public_key=None):
        """Get api sample of key pairs post request."""
        key_name = 'keypair-' + str(uuid_lib.uuid4())
        response = self._do_post('os-keypairs', 'keypairs-post-req',
                                 {'keypair_name': key_name})
        subs = self._get_regexes()
        subs['keypair_name'] = '(%s)' % key_name
        self._verify_response('keypairs-post-resp', subs, response, 200)
        # NOTE(maurosr): return the key_name is necessary cause the
        # verification returns the label of the last compared information in
        # the response, not necessarily the key name.
        return key_name

    def test_keypairs_import_key_post(self):
        # Get api sample of key pairs post to import user's key.
        key_name = 'keypair-' + str(uuid_lib.uuid4())
        subs = {
            'keypair_name': key_name,
            'public_key': "ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAAAgQDx8nkQv/zgGg"
                          "B4rMYmIf+6A4l6Rr+o/6lHBQdW5aYd44bd8JttDCE/F/pNRr0l"
                          "RE+PiqSPO8nDPHw0010JeMH9gYgnnFlyY3/OcJ02RhIPyyxYpv"
                          "9FhY+2YiUkpwFOcLImyrxEsYXpD/0d3ac30bNH6Sw9JD9UZHYc"
                          "pSxsIbECHw== Generated-by-Nova"
        }
        response = self._do_post('os-keypairs', 'keypairs-import-post-req',
                                 subs)
        subs = self._get_regexes()
        subs['keypair_name'] = '(%s)' % key_name
        self._verify_response('keypairs-import-post-resp', subs, response, 200)

    def test_keypairs_list(self):
        # Get api sample of key pairs list request.
        key_name = self.test_keypairs_post()
        response = self._do_get('os-keypairs')
        subs = self._get_regexes()
        subs['keypair_name'] = '(%s)' % key_name
        self._verify_response('keypairs-list-resp', subs, response, 200)

    def test_keypairs_get(self):
        # Get api sample of key pairs get request.
        key_name = self.test_keypairs_post()
        response = self._do_get('os-keypairs/%s' % key_name)
        subs = self._get_regexes()
        subs['keypair_name'] = '(%s)' % key_name
        self._verify_response('keypairs-get-resp', subs, response, 200)


class RescueJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                     ".rescue.Rescue")

    def _rescue(self, uuid):
        req_subs = {
            'password': 'MySecretPass'
        }
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-rescue-req', req_subs)
        self._verify_response('server-rescue', req_subs, response, 200)

    def _unrescue(self, uuid):
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-unrescue-req', {})
        self.assertEqual(response.status_code, 202)

    def test_server_rescue(self):
        uuid = self._post_server()

        self._rescue(uuid)

        # Do a server get to make sure that the 'RESCUE' state is set
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['status'] = 'RESCUE'

        self._verify_response('server-get-resp-rescue', subs, response, 200)

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

        self._verify_response('server-get-resp-unrescue', subs, response, 200)


class ExtendedRescueWithImageJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                      ".extended_rescue_with_image.Extended_rescue_with_image")

    def _get_flags(self):
        f = super(ExtendedRescueWithImageJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        # ExtendedRescueWithImage extension also needs Rescue to be loaded.
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.rescue.Rescue')
        return f

    def _rescue(self, uuid):
        req_subs = {
            'password': 'MySecretPass',
            'rescue_image_ref': fake.get_valid_image_id()
        }
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-rescue-req', req_subs)
        self._verify_response('server-rescue', req_subs, response, 200)

    def test_server_rescue(self):
        uuid = self._post_server()

        self._rescue(uuid)

        # Do a server get to make sure that the 'RESCUE' state is set
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['status'] = 'RESCUE'

        self._verify_response('server-get-resp-rescue', subs, response, 200)


class VirtualInterfacesJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                     ".virtual_interfaces.Virtual_interfaces")

    def test_vifs_list(self):
        uuid = self._post_server()

        response = self._do_get('servers/%s/os-virtual-interfaces' % uuid)

        subs = self._get_regexes()
        subs['mac_addr'] = '(?:[a-f0-9]{2}:){5}[a-f0-9]{2}'

        self._verify_response('vifs-list-resp', subs, response, 200)


class UsedLimitsSamplesJsonTest(ApiSampleTestBaseV2):
    extension_name = ("nova.api.openstack.compute.contrib.used_limits."
                      "Used_limits")

    def test_get_used_limits(self):
        # Get api sample to used limits.
        response = self._do_get('limits')
        subs = self._get_regexes()
        self._verify_response('usedlimits-get-resp', subs, response, 200)


class UsedLimitsForAdminSamplesJsonTest(ApiSampleTestBaseV2):
    ADMIN_API = True
    extends_name = ("nova.api.openstack.compute.contrib.used_limits."
                    "Used_limits")
    extension_name = (
        "nova.api.openstack.compute.contrib.used_limits_for_admin."
        "Used_limits_for_admin")

    def test_get_used_limits_for_admin(self):
        tenant_id = 'openstack'
        response = self._do_get('limits?tenant_id=%s' % tenant_id)
        subs = self._get_regexes()
        return self._verify_response('usedlimitsforadmin-get-resp', subs,
                                     response, 200)


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
        subs.update(self._get_regexes())
        self._verify_response('availability-zone-post-resp', subs,
                              response, 202)


class ConsoleAuthTokensSampleJsonTests(ServersSampleBase):
    ADMIN_API = True
    extends_name = ("nova.api.openstack.compute.contrib.consoles.Consoles")
    extension_name = ("nova.api.openstack.compute.contrib.console_auth_tokens."
                      "Console_auth_tokens")

    def _get_console_url(self, data):
        return jsonutils.loads(data)["console"]["url"]

    def _get_console_token(self, uuid):
        response = self._do_post('servers/%s/action' % uuid,
                                 'get-rdp-console-post-req',
                                {'action': 'os-getRDPConsole'})

        url = self._get_console_url(response.content)
        return re.match('.+?token=([^&]+)', url).groups()[0]

    def test_get_console_connect_info(self):
        self.flags(enabled=True, group='rdp')

        uuid = self._post_server()
        token = self._get_console_token(uuid)

        response = self._do_get('os-console-auth-tokens/%s' % token)

        subs = self._get_regexes()
        subs["uuid"] = uuid
        subs["host"] = r"[\w\.\-]+"
        subs["port"] = "[0-9]+"
        subs["internal_access_path"] = ".*"
        self._verify_response('get-console-connect-info-get-resp', subs,
                              response, 200)


class QuotasSampleJsonTests(ApiSampleTestBaseV2):
    ADMIN_API = True
    extension_name = "nova.api.openstack.compute.contrib.quotas.Quotas"

    def test_show_quotas(self):
        # Get api sample to show quotas.
        response = self._do_get('os-quota-sets/fake_tenant')
        self._verify_response('quotas-show-get-resp', {}, response, 200)

    def test_show_quotas_defaults(self):
        # Get api sample to show quotas defaults.
        response = self._do_get('os-quota-sets/fake_tenant/defaults')
        self._verify_response('quotas-show-defaults-get-resp',
                              {}, response, 200)

    def test_update_quotas(self):
        # Get api sample to update quotas.
        response = self._do_put('os-quota-sets/fake_tenant',
                                'quotas-update-post-req',
                                {})
        self._verify_response('quotas-update-post-resp', {}, response, 200)


class ExtendedQuotasSampleJsonTests(ApiSampleTestBaseV2):
    ADMIN_API = True
    extends_name = "nova.api.openstack.compute.contrib.quotas.Quotas"
    extension_name = ("nova.api.openstack.compute.contrib"
                      ".extended_quotas.Extended_quotas")

    def test_delete_quotas(self):
        # Get api sample to delete quota.
        response = self._do_delete('os-quota-sets/fake_tenant')
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')

    def test_update_quotas(self):
        # Get api sample to update quotas.
        response = self._do_put('os-quota-sets/fake_tenant',
                                'quotas-update-post-req',
                                {})
        return self._verify_response('quotas-update-post-resp', {},
                                     response, 200)


class UserQuotasSampleJsonTests(ApiSampleTestBaseV2):
    ADMIN_API = True
    extends_name = "nova.api.openstack.compute.contrib.quotas.Quotas"
    extension_name = ("nova.api.openstack.compute.contrib"
                      ".user_quotas.User_quotas")

    def fake_load(self, *args):
        return True

    def test_show_quotas_for_user(self):
        # Get api sample to show quotas for user.
        response = self._do_get('os-quota-sets/fake_tenant?user_id=1')
        self._verify_response('user-quotas-show-get-resp', {}, response, 200)

    def test_delete_quotas_for_user(self):
        # Get api sample to delete quota for user.
        self.stubs.Set(extensions.ExtensionManager, "is_loaded",
                self.fake_load)
        response = self._do_delete('os-quota-sets/fake_tenant?user_id=1')
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, '')

    def test_update_quotas_for_user(self):
        # Get api sample to update quotas for user.
        response = self._do_put('os-quota-sets/fake_tenant?user_id=1',
                                'user-quotas-update-post-req',
                                {})
        return self._verify_response('user-quotas-update-post-resp', {},
                                     response, 200)


class ExtendedIpsSampleJsonTests(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                      ".extended_ips.Extended_ips")

    def test_show(self):
        uuid = self._post_server()
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['hypervisor_hostname'] = r'[\w\.\-]+'
        self._verify_response('server-get-resp', subs, response, 200)

    def test_detail(self):
        uuid = self._post_server()
        response = self._do_get('servers/detail')
        subs = self._get_regexes()
        subs['id'] = uuid
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('servers-detail-resp', subs, response, 200)


class ExtendedIpsMacSampleJsonTests(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                      ".extended_ips_mac.Extended_ips_mac")

    def test_show(self):
        uuid = self._post_server()
        response = self._do_get('servers/%s' % uuid)
        self.assertEqual(response.status_code, 200)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['hypervisor_hostname'] = r'[\w\.\-]+'
        subs['mac_addr'] = '(?:[a-f0-9]{2}:){5}[a-f0-9]{2}'
        self._verify_response('server-get-resp', subs, response, 200)

    def test_detail(self):
        uuid = self._post_server()
        response = self._do_get('servers/detail')
        self.assertEqual(response.status_code, 200)
        subs = self._get_regexes()
        subs['id'] = uuid
        subs['hostid'] = '[a-f0-9]+'
        subs['mac_addr'] = '(?:[a-f0-9]{2}:){5}[a-f0-9]{2}'
        self._verify_response('servers-detail-resp', subs, response, 200)


class ExtendedVIFNetSampleJsonTests(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
          ".extended_virtual_interfaces_net.Extended_virtual_interfaces_net")

    def _get_flags(self):
        f = super(ExtendedVIFNetSampleJsonTests, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        # extended_virtual_interfaces_net_update also
        # needs virtual_interfaces to be loaded
        f['osapi_compute_extension'].append(
            ('nova.api.openstack.compute.contrib'
             '.virtual_interfaces.Virtual_interfaces'))
        return f

    def test_vifs_list(self):
        uuid = self._post_server()

        response = self._do_get('servers/%s/os-virtual-interfaces' % uuid)
        self.assertEqual(response.status_code, 200)

        subs = self._get_regexes()
        subs['mac_addr'] = '(?:[a-f0-9]{2}:){5}[a-f0-9]{2}'

        self._verify_response('vifs-list-resp', subs, response, 200)


class ServerPasswordSampleJsonTests(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib.server_password."
                      "Server_password")

    def test_get_password(self):

        # Mock password since there is no api to set it
        def fake_ext_password(*args, **kwargs):
            return ("xlozO3wLCBRWAa2yDjCCVx8vwNPypxnypmRYDa/zErlQ+EzPe1S/"
                    "Gz6nfmC52mOlOSCRuUOmG7kqqgejPof6M7bOezS387zjq4LSvvwp"
                    "28zUknzy4YzfFGhnHAdai3TxUJ26pfQCYrq8UTzmKF2Bq8ioSEtV"
                    "VzM0A96pDh8W2i7BOz6MdoiVyiev/I1K2LsuipfxSJR7Wdke4zNX"
                    "JjHHP2RfYsVbZ/k9ANu+Nz4iIH8/7Cacud/pphH7EjrY6a4RZNrj"
                    "QskrhKYed0YERpotyjYk1eDtRe72GrSiXteqCM4biaQ5w3ruS+Ac"
                    "X//PXk3uJ5kC7d67fPXaVz4WaQRYMg==")
        self.stubs.Set(password, "extract_password", fake_ext_password)
        uuid = self._post_server()
        response = self._do_get('servers/%s/os-server-password' % uuid)
        subs = self._get_regexes()
        subs['encrypted_password'] = fake_ext_password().replace('+', '\\+')
        self._verify_response('get-password-resp', subs, response, 200)

    def test_reset_password(self):
        uuid = self._post_server()
        response = self._do_delete('servers/%s/os-server-password' % uuid)
        self.assertEqual(response.status_code, 204)


class DiskConfigJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib.disk_config."
                      "Disk_config")

    def test_list_servers_detail(self):
        uuid = self._post_server(use_common_server_api_samples=False)
        response = self._do_get('servers/detail')
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        self._verify_response('list-servers-detail-get', subs, response, 200)

    def test_get_server(self):
        uuid = self._post_server(use_common_server_api_samples=False)
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('server-get-resp', subs, response, 200)

    def test_update_server(self):
        uuid = self._post_server(use_common_server_api_samples=False)
        response = self._do_put('servers/%s' % uuid,
                                'server-update-put-req', {})
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('server-update-put-resp', subs, response, 200)

    def test_resize_server(self):
        self.flags(allow_resize_to_same_host=True)
        uuid = self._post_server(use_common_server_api_samples=False)
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-resize-post-req', {})
        self.assertEqual(response.status_code, 202)
        # NOTE(tmello): Resize does not return response body
        # Bug #1085213.
        self.assertEqual(response.content, "")

    def test_rebuild_server(self):
        uuid = self._post_server(use_common_server_api_samples=False)
        subs = {
            'image_id': fake.get_valid_image_id(),
            'host': self._get_host(),
        }
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-action-rebuild-req', subs)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('server-action-rebuild-resp',
                              subs, response, 202)

    def test_get_image(self):
        image_id = fake.get_valid_image_id()
        response = self._do_get('images/%s' % image_id)
        subs = self._get_regexes()
        subs['image_id'] = image_id
        self._verify_response('image-get-resp', subs, response, 200)

    def test_list_images(self):
        response = self._do_get('images/detail')
        subs = self._get_regexes()
        self._verify_response('image-list-resp', subs, response, 200)


class BlockDeviceMappingV2BootJsonTest(ServersSampleBase):
    extension_name = ('nova.api.openstack.compute.contrib.'
                      'block_device_mapping_v2_boot.'
                      'Block_device_mapping_v2_boot')

    def _get_flags(self):
        f = super(BlockDeviceMappingV2BootJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        # We need the volumes extension as well
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.volumes.Volumes')
        return f

    def test_servers_post_with_bdm_v2(self):
        self.stubs.Set(cinder.API, 'get', fakes.stub_volume_get)
        self.stubs.Set(cinder.API, 'check_attach',
                       fakes.stub_volume_check_attach)
        return self._post_server()


class ExtendedAvailabilityZoneJsonTests(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib"
                                ".extended_availability_zone"
                                ".Extended_availability_zone")

    def test_show(self):
        uuid = self._post_server()
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('server-get-resp', subs, response, 200)

    def test_detail(self):
        self._post_server()
        response = self._do_get('servers/detail')
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('servers-detail-resp', subs, response, 200)


class ConfigDriveSampleJsonTest(ServersSampleBase):
    extension_name = ("nova.api.openstack.compute.contrib.config_drive."
                      "Config_drive")

    def setUp(self):
        super(ConfigDriveSampleJsonTest, self).setUp()
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        fake.stub_out_image_service(self.stubs)

    def test_config_drive_show(self):
        uuid = self._post_server()
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        # config drive can be a string for True or empty value for False
        subs['cdrive'] = '.*'
        self._verify_response('server-config-drive-get-resp', subs,
                              response, 200)

    def test_config_drive_detail(self):
        self._post_server()
        response = self._do_get('servers/detail')
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        # config drive can be a string for True or empty value for False
        subs['cdrive'] = '.*'
        self._verify_response('servers-config-drive-details-resp',
                              subs, response, 200)


@mock.patch.object(service_group_api.API, "service_is_up", lambda _: True)
class HypervisorsSampleJsonTests(ApiSampleTestBaseV2):
    ADMIN_API = True
    extension_name = ("nova.api.openstack.compute.contrib.hypervisors."
                      "Hypervisors")

    def test_hypervisors_list(self):
        response = self._do_get('os-hypervisors')
        self._verify_response('hypervisors-list-resp', {}, response, 200)

    def test_hypervisors_search(self):
        response = self._do_get('os-hypervisors/fake/search')
        self._verify_response('hypervisors-search-resp', {}, response, 200)

    def test_hypervisors_servers(self):
        response = self._do_get('os-hypervisors/fake/servers')
        self._verify_response('hypervisors-servers-resp', {}, response, 200)

    def test_hypervisors_show(self):
        hypervisor_id = 1
        subs = {
            'hypervisor_id': hypervisor_id
        }
        response = self._do_get('os-hypervisors/%s' % hypervisor_id)
        subs.update(self._get_regexes())
        self._verify_response('hypervisors-show-resp', subs, response, 200)

    def test_hypervisors_statistics(self):
        response = self._do_get('os-hypervisors/statistics')
        self._verify_response('hypervisors-statistics-resp', {}, response, 200)

    def test_hypervisors_uptime(self):
        def fake_get_host_uptime(self, context, hyp):
            return (" 08:32:11 up 93 days, 18:25, 12 users,  load average:"
                    " 0.20, 0.12, 0.14")

        self.stubs.Set(compute_api.HostAPI,
                       'get_host_uptime', fake_get_host_uptime)
        hypervisor_id = 1
        response = self._do_get('os-hypervisors/%s/uptime' % hypervisor_id)
        subs = {
            'hypervisor_id': hypervisor_id,
        }
        self._verify_response('hypervisors-uptime-resp', subs, response, 200)


class ExtendedHypervisorsJsonTest(ApiSampleTestBaseV2):
    ADMIN_API = True
    extends_name = ("nova.api.openstack.compute.contrib."
                    "hypervisors.Hypervisors")
    extension_name = ("nova.api.openstack.compute.contrib."
                      "extended_hypervisors.Extended_hypervisors")

    def test_hypervisors_show_with_ip(self):
        hypervisor_id = 1
        subs = {
            'hypervisor_id': hypervisor_id
        }
        response = self._do_get('os-hypervisors/%s' % hypervisor_id)
        subs.update(self._get_regexes())
        self._verify_response('hypervisors-show-with-ip-resp',
                              subs, response, 200)


class HypervisorStatusJsonTest(ApiSampleTestBaseV2):
    ADMIN_API = True
    extends_name = ("nova.api.openstack.compute.contrib."
                    "hypervisors.Hypervisors")
    extension_name = ("nova.api.openstack.compute.contrib."
                      "hypervisor_status.Hypervisor_status")

    def test_hypervisors_show_with_status(self):
        hypervisor_id = 1
        subs = {
            'hypervisor_id': hypervisor_id
        }
        response = self._do_get('os-hypervisors/%s' % hypervisor_id)
        subs.update(self._get_regexes())
        self._verify_response('hypervisors-show-with-status-resp',
                              subs, response, 200)


@mock.patch("nova.servicegroup.API.service_is_up", return_value=True)
class HypervisorsCellsSampleJsonTests(ApiSampleTestBaseV2):
    ADMIN_API = True
    extension_name = ("nova.api.openstack.compute.contrib.hypervisors."
                      "Hypervisors")

    def setUp(self):
        self.flags(enable=True, cell_type='api', group='cells')
        super(HypervisorsCellsSampleJsonTests, self).setUp()

    def test_hypervisor_uptime(self, mocks):
        fake_hypervisor = objects.ComputeNode(id=1, host='fake-mini',
                                              hypervisor_hostname='fake-mini')

        def fake_get_host_uptime(self, context, hyp):
            return (" 08:32:11 up 93 days, 18:25, 12 users,  load average:"
                    " 0.20, 0.12, 0.14")

        def fake_compute_node_get(self, context, hyp):
            return fake_hypervisor

        def fake_service_get_by_compute_host(self, context, host):
            return cells_utils.ServiceProxy(
                objects.Service(id=1, host='fake-mini', disabled=False,
                                disabled_reason=None),
                'cell1')

        self.stubs.Set(cells_api.HostAPI, 'compute_node_get',
                       fake_compute_node_get)
        self.stubs.Set(cells_api.HostAPI, 'service_get_by_compute_host',
                       fake_service_get_by_compute_host)

        self.stubs.Set(cells_api.HostAPI,
                       'get_host_uptime', fake_get_host_uptime)
        hypervisor_id = fake_hypervisor['id']
        response = self._do_get('os-hypervisors/%s/uptime' % hypervisor_id)
        subs = {'hypervisor_id': hypervisor_id}
        self._verify_response('hypervisors-uptime-resp', subs, response, 200)


class PreserveEphemeralOnRebuildJsonTest(ServersSampleBase):
    extension_name = ('nova.api.openstack.compute.contrib.'
                      'preserve_ephemeral_rebuild.'
                      'Preserve_ephemeral_rebuild')

    def _test_server_action(self, uuid, action,
                            subs=None, resp_tpl=None, code=202):
        subs = subs or {}
        subs.update({'action': action})
        response = self._do_post('servers/%s/action' % uuid,
                                 'server-action-%s' % action.lower(),
                                 subs)
        if resp_tpl:
            subs.update(self._get_regexes())
            self._verify_response(resp_tpl, subs, response, code)
        else:
            self.assertEqual(response.status_code, code)
            self.assertEqual(response.content, "")

    def test_rebuild_server_preserve_ephemeral_false(self):
        uuid = self._post_server()
        image = self.api.get_images()[0]['id']
        subs = {'host': self._get_host(),
                'uuid': image,
                'name': 'foobar',
                'pass': 'seekr3t',
                'ip': '1.2.3.4',
                'ip6': 'fe80::100',
                'hostid': '[a-f0-9]+',
                'preserve_ephemeral': 'false'}
        self._test_server_action(uuid, 'rebuild', subs,
                                 'server-action-rebuild-resp')

    def test_rebuild_server_preserve_ephemeral_true(self):
        image = self.api.get_images()[0]['id']
        subs = {'host': self._get_host(),
                'uuid': image,
                'name': 'new-server-test',
                'pass': 'seekr3t',
                'ip': '1.2.3.4',
                'ip6': 'fe80::100',
                'hostid': '[a-f0-9]+',
                'preserve_ephemeral': 'true'}

        def fake_rebuild(self_, context, instance, image_href, admin_password,
                         **kwargs):
            self.assertTrue(kwargs['preserve_ephemeral'])
        self.stubs.Set(compute_api.API, 'rebuild', fake_rebuild)

        instance_uuid = self._post_server()
        response = self._do_post('servers/%s/action' % instance_uuid,
                                 'server-action-rebuild', subs)
        self.assertEqual(response.status_code, 202)


class ServerGroupQuotas_LimitsSampleJsonTest(LimitsSampleJsonTest):
    sample_dir = None
    extension_name = ("nova.api.openstack.compute.contrib."
                      "server_group_quotas.Server_group_quotas")


class ServerGroupQuotas_UsedLimitsSamplesJsonTest(UsedLimitsSamplesJsonTest):
    extension_name = ("nova.api.openstack.compute.contrib."
               "server_group_quotas.Server_group_quotas")
    extends_name = ("nova.api.openstack.compute.contrib.used_limits."
                    "Used_limits")


class ServerGroupQuotas_QuotasSampleJsonTests(QuotasSampleJsonTests):
    extension_name = ("nova.api.openstack.compute.contrib."
               "server_group_quotas.Server_group_quotas")
    extends_name = "nova.api.openstack.compute.contrib.quotas.Quotas"
