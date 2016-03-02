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

from oslo_config import cfg

from nova.tests.functional.api_sample_tests import api_sample_base
from nova.tests.unit.image import fake

CONF = cfg.CONF
CONF.import_opt('osapi_compute_extension',
                'nova.api.openstack.compute.legacy_v2.extensions')


class ServersSampleBase(api_sample_base.ApiSampleTestBaseV21):
    extra_extensions_to_load = ["os-access-ips"]
    microversion = None

    def _post_server(self, use_common_server_api_samples=True):
        # param use_common_server_api_samples: Boolean to set whether tests use
        # common sample files for server post request and response.
        # Default is True which means _get_sample_path method will fetch the
        # common server sample files from 'servers' directory.
        # Set False if tests need to use extension specific sample files

        subs = {
            'image_id': fake.get_valid_image_id(),
            'host': self._get_host(),
            'compute_endpoint': self._get_compute_endpoint(),
            'versioned_compute_endpoint': self._get_vers_compute_endpoint(),
            'glance_host': self._get_glance_host(),
            'access_ip_v4': '1.2.3.4',
            'access_ip_v6': '80fe::'
        }
        # TODO(gmann): Remove this hack once all tests using this common
        # _post_server method are enabled with all extension.
        # This is added to avoid all tests updates together.
        post_req_template = 'server-post-req'
        post_resp_template = 'server-post-resp'
        if self.all_extensions and use_common_server_api_samples:
            post_req_template = 'server-create-req'
            post_resp_template = 'server-create-resp'

        orig_value = self.__class__._use_common_server_api_samples
        orig_sample_dir = self.__class__.sample_dir
        try:
            self.__class__._use_common_server_api_samples = (
                                        use_common_server_api_samples)
            response = self._do_post('servers', post_req_template, subs)
            status = self._verify_response(post_resp_template, subs,
                                           response, 202)
            return status
        finally:
            self.__class__._use_common_server_api_samples = orig_value
            self.__class__.sample_dir = orig_sample_dir

    def setUp(self):
        super(ServersSampleBase, self).setUp()
        self.api.microversion = self.microversion


class ServersSampleJsonTest(ServersSampleBase):
    sample_dir = 'servers'
    microversion = None

    def _get_flags(self):
        f = super(ServersSampleBase, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.keypairs.Keypairs')
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.extended_ips.Extended_ips')
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.extended_ips_mac.'
            'Extended_ips_mac')
        return f

    def test_servers_post(self):
        return self._post_server()

    def test_servers_get(self):
        uuid = self.test_servers_post()
        response = self._do_get('servers/%s' % uuid)
        subs = {}
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['hypervisor_hostname'] = r'[\w\.\-]+'
        subs['mac_addr'] = '(?:[a-f0-9]{2}:){5}[a-f0-9]{2}'
        subs['access_ip_v4'] = '1.2.3.4'
        subs['access_ip_v6'] = '80fe::'
        self._verify_response('server-get-resp', subs, response, 200)

    def test_servers_list(self):
        uuid = self._post_server()
        response = self._do_get('servers')
        subs = {'id': uuid}
        self._verify_response('servers-list-resp', subs, response, 200)

    def test_servers_details(self):
        uuid = self.test_servers_post()
        response = self._do_get('servers/detail')
        subs = {}
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['hypervisor_hostname'] = r'[\w\.\-]+'
        subs['mac_addr'] = '(?:[a-f0-9]{2}:){5}[a-f0-9]{2}'
        subs['access_ip_v4'] = '1.2.3.4'
        subs['access_ip_v6'] = '80fe::'
        self._verify_response('servers-details-resp', subs, response, 200)


class ServersSampleJson29Test(ServersSampleJsonTest):
    microversion = '2.9'
    # NOTE(gmann): microversion tests do not need to run for v2 API
    # so defining scenarios only for v2.9 which will run the original tests
    # by appending '(v2_9)' in test_id.
    scenarios = [('v2_9', {'api_major_version': 'v2.1'})]


class ServersSampleJson219Test(ServersSampleJsonTest):
    microversion = '2.19'
    sample_dir = 'servers'
    scenarios = [('v2_19', {'api_major_version': 'v2.1'})]

    def test_servers_post(self):
        return self._post_server(False)

    def test_servers_put(self):
        uuid = self.test_servers_post()
        response = self._do_put('servers/%s' % uuid, 'server-put-req', {})
        subs = {
            'image_id': fake.get_valid_image_id(),
            'hostid': '[a-f0-9]+',
            'glance_host': self._get_glance_host(),
            'access_ip_v4': '1.2.3.4',
            'access_ip_v6': '80fe::'
        }
        self._verify_response('server-put-resp', subs, response, 200)


class ServersUpdateSampleJsonTest(ServersSampleBase):
    sample_dir = 'servers'

    # TODO(gmann): This will be removed once all API tests runs for
    # all extension enable.
    all_extensions = True

    def test_update_server(self):
        uuid = self._post_server()
        subs = {}
        subs['hostid'] = '[a-f0-9]+'
        subs['access_ip_v4'] = '1.2.3.4'
        subs['access_ip_v6'] = '80fe::'
        response = self._do_put('servers/%s' % uuid,
                                'server-update-req', subs)
        self._verify_response('server-update-resp', subs, response, 200)


class ServerSortKeysJsonTests(ServersSampleBase):
    sample_dir = 'servers-sort'

    def _get_flags(self):
        f = super(ServerSortKeysJsonTests, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.server_sort_keys.'
            'Server_sort_keys')
        return f

    def test_servers_list(self):
        self._post_server()
        response = self._do_get('servers?sort_key=display_name&sort_dir=asc')
        self._verify_response('server-sort-keys-list-resp', {}, response,
                              200)


class ServersSampleAllExtensionJsonTest(ServersSampleJsonTest):
    all_extensions = True
    sample_dir = None


class ServersActionsJsonTest(ServersSampleBase):
    sample_dir = 'servers'

    def _test_server_action(self, uuid, action, req_tpl,
                            subs=None, resp_tpl=None, code=202):
        subs = subs or {}
        subs.update({'action': action,
                     'glance_host': self._get_glance_host()})
        response = self._do_post('servers/%s/action' % uuid,
                                 req_tpl,
                                 subs)
        if resp_tpl:
            self._verify_response(resp_tpl, subs, response, code)
        else:
            self.assertEqual(code, response.status_code)
            self.assertEqual("", response.content)

    def test_server_reboot_hard(self):
        uuid = self._post_server()
        self._test_server_action(uuid, "reboot",
                                 'server-action-reboot',
                                 {"type": "HARD"})

    def test_server_reboot_soft(self):
        uuid = self._post_server()
        self._test_server_action(uuid, "reboot",
                                 'server-action-reboot',
                                 {"type": "SOFT"})

    def test_server_rebuild(self):
        uuid = self._post_server()
        image = fake.get_valid_image_id()
        params = {
            'uuid': image,
            'name': 'foobar',
            'pass': 'seekr3t',
            'hostid': '[a-f0-9]+',
            'access_ip_v4': '1.2.3.4',
            'access_ip_v6': '80fe::',
        }

        resp = self._do_post('servers/%s/action' % uuid,
                             'server-action-rebuild', params)
        subs = params.copy()
        del subs['uuid']
        self._verify_response('server-action-rebuild-resp', subs, resp, 202)

    def test_server_resize(self):
        self.flags(allow_resize_to_same_host=True)
        uuid = self._post_server()
        self._test_server_action(uuid, "resize",
                                 'server-action-resize',
                                 {"id": '2',
                                  "host": self._get_host()})
        return uuid

    def test_server_revert_resize(self):
        uuid = self.test_server_resize()
        self._test_server_action(uuid, "revertResize",
                                 'server-action-revert-resize')

    def test_server_confirm_resize(self):
        uuid = self.test_server_resize()
        self._test_server_action(uuid, "confirmResize",
                                 'server-action-confirm-resize',
                                 code=204)

    def test_server_create_image(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'createImage',
                                 'server-action-create-image',
                                 {'name': 'foo-image'})


class ServersActionsJson219Test(ServersSampleBase):
    microversion = '2.19'
    sample_dir = 'servers'
    scenarios = [('v2_19', {'api_major_version': 'v2.1'})]

    def test_server_rebuild(self):
        uuid = self._post_server()
        image = fake.get_valid_image_id()
        params = {
            'uuid': image,
            'name': 'foobar',
            'description': 'description of foobar',
            'pass': 'seekr3t',
            'hostid': '[a-f0-9]+',
            'access_ip_v4': '1.2.3.4',
            'access_ip_v6': '80fe::',
        }

        resp = self._do_post('servers/%s/action' % uuid,
                             'server-action-rebuild', params)
        subs = params.copy()
        del subs['uuid']
        self._verify_response('server-action-rebuild-resp', subs, resp, 202)


class ServersActionsAllJsonTest(ServersActionsJsonTest):
    all_extensions = True
    sample_dir = None


class ServerStartStopJsonTest(ServersSampleBase):
    sample_dir = 'servers'

    def _get_flags(self):
        f = super(ServerStartStopJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.contrib.server_start_stop.'
            'Server_start_stop')
        return f

    def _test_server_action(self, uuid, action, req_tpl):
        response = self._do_post('servers/%s/action' % uuid,
                                 req_tpl,
                                 {'action': action})
        self.assertEqual(202, response.status_code)
        self.assertEqual("", response.content)

    def test_server_start(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'os-stop', 'server-action-stop')
        self._test_server_action(uuid, 'os-start', 'server-action-start')

    def test_server_stop(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'os-stop', 'server-action-stop')


class ServersSampleMultiStatusJsonTest(ServersSampleBase):
    sample_dir = 'servers'
    extra_extensions_to_load = ["os-access-ips"]

    def _get_flags(self):
        f = super(ServersSampleMultiStatusJsonTest, self)._get_flags()
        f['osapi_compute_extension'] = CONF.osapi_compute_extension[:]
        f['osapi_compute_extension'].append(
            'nova.api.openstack.compute.legacy_v2.contrib.'
            'server_list_multi_status.Server_list_multi_status')
        return f

    def test_servers_list(self):
        uuid = self._post_server()
        response = self._do_get('servers?status=active&status=error')
        subs = {'id': uuid}
        self._verify_response('servers-list-resp', subs, response, 200)


class ServerTriggerCrashDumpJsonTest(ServersSampleBase):
    sample_dir = 'servers'
    microversion = '2.17'
    scenarios = [('v2_17', {'api_major_version': 'v2.1'})]

    def test_trigger_crash_dump(self):
        uuid = self._post_server()

        response = self._do_post('servers/%s/action' % uuid,
                                 'server-action-trigger-crash-dump',
                                 {})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.content, "")
