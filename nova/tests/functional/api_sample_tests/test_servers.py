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

import base64
import time

import six

from nova.api.openstack import api_version_request as avr
import nova.conf
from nova.tests.functional.api_sample_tests import api_sample_base
from nova.tests.unit.api.openstack import fakes
from nova.tests.unit.image import fake

CONF = nova.conf.CONF


class ServersSampleBase(api_sample_base.ApiSampleTestBaseV21):
    microversion = None
    sample_dir = 'servers'

    user_data_contents = six.b('#!/bin/bash\n/bin/su\necho "I am in you!"\n')
    user_data = base64.b64encode(user_data_contents)

    common_req_names = [
        (None, '2.36', 'server-create-req'),
        ('2.37', '2.56', 'server-create-req-v237'),
        ('2.57', None, 'server-create-req-v257')
    ]

    def _get_request_name(self, use_common):
        if not use_common:
            return 'server-create-req'

        api_version = self.microversion or '2.1'
        for min, max, name in self.common_req_names:
            if avr.APIVersionRequest(api_version).matches(
                    avr.APIVersionRequest(min), avr.APIVersionRequest(max)):
                return name

    def _post_server(self, use_common_server_api_samples=True, name=None):
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
            'access_ip_v6': '80fe::',
            'user_data': (self.user_data if six.PY2
                          else self.user_data.decode('utf-8')),
            'uuid': '[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}'
                    '-[0-9a-f]{4}-[0-9a-f]{12}',
            'name': 'new-server-test' if name is None else name,
        }

        orig_value = self.__class__._use_common_server_api_samples
        try:
            self.__class__._use_common_server_api_samples = (
                                        use_common_server_api_samples)
            response = self._do_post('servers', self._get_request_name(
                use_common_server_api_samples), subs)
            status = self._verify_response('server-create-resp', subs,
                                           response, 202)
            return status
        finally:
            self.__class__._use_common_server_api_samples = orig_value

    def setUp(self):
        super(ServersSampleBase, self).setUp()
        self.api.microversion = self.microversion


class ServersSampleJsonTest(ServersSampleBase):
    # This controls whether or not we use the common server API sample
    # for server post req/resp.
    use_common_server_post = True
    microversion = None

    def test_servers_post(self):
        return self._post_server(
            use_common_server_api_samples=self.use_common_server_post)

    def test_servers_get(self):
        self.stub_out(
            'nova.db.api.block_device_mapping_get_all_by_instance_uuids',
            fakes.stub_bdm_get_all_by_instance_uuids)
        uuid = self.test_servers_post()
        response = self._do_get('servers/%s' % uuid)
        subs = {}
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['instance_name'] = 'instance-\d{8}'
        subs['hypervisor_hostname'] = r'[\w\.\-]+'
        subs['hostname'] = r'[\w\.\-]+'
        subs['mac_addr'] = '(?:[a-f0-9]{2}:){5}[a-f0-9]{2}'
        subs['access_ip_v4'] = '1.2.3.4'
        subs['access_ip_v6'] = '80fe::'
        subs['user_data'] = (self.user_data if six.PY2
                             else self.user_data.decode('utf-8'))
        # config drive can be a string for True or empty value for False
        subs['cdrive'] = '.*'
        self._verify_response('server-get-resp', subs, response, 200)

    def test_servers_list(self):
        uuid = self._post_server()
        response = self._do_get('servers?limit=1')
        subs = {'id': uuid}
        self._verify_response('servers-list-resp', subs, response, 200)

    def test_servers_details(self):
        self.stub_out(
            'nova.db.api.block_device_mapping_get_all_by_instance_uuids',
            fakes.stub_bdm_get_all_by_instance_uuids)
        uuid = self.test_servers_post()
        response = self._do_get('servers/detail?limit=1')
        subs = {}
        subs['hostid'] = '[a-f0-9]+'
        subs['id'] = uuid
        subs['instance_name'] = 'instance-\d{8}'
        subs['hypervisor_hostname'] = r'[\w\.\-]+'
        subs['hostname'] = r'[\w\.\-]+'
        subs['mac_addr'] = '(?:[a-f0-9]{2}:){5}[a-f0-9]{2}'
        subs['access_ip_v4'] = '1.2.3.4'
        subs['access_ip_v6'] = '80fe::'
        subs['user_data'] = (self.user_data if six.PY2
                             else self.user_data.decode('utf-8'))
        # config drive can be a string for True or empty value for False
        subs['cdrive'] = '.*'
        self._verify_response('servers-details-resp', subs, response, 200)


class ServersSampleJson23Test(ServersSampleJsonTest):
    microversion = '2.3'
    scenarios = [('v2_3', {'api_major_version': 'v2.1'})]


class ServersSampleJson29Test(ServersSampleJsonTest):
    microversion = '2.9'
    # NOTE(gmann): microversion tests do not need to run for v2 API
    # so defining scenarios only for v2.9 which will run the original tests
    # by appending '(v2_9)' in test_id.
    scenarios = [('v2_9', {'api_major_version': 'v2.1'})]


class ServersSampleJson216Test(ServersSampleJsonTest):
    microversion = '2.16'
    scenarios = [('v2_16', {'api_major_version': 'v2.1'})]


class ServersSampleJson219Test(ServersSampleJsonTest):
    microversion = '2.19'
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


class ServersSampleJson232Test(ServersSampleBase):
    microversion = '2.32'
    sample_dir = 'servers'
    scenarios = [('v2_32', {'api_major_version': 'v2.1'})]

    def test_servers_post(self):
        self._post_server(use_common_server_api_samples=False)


class ServersSampleJson237Test(ServersSampleBase):
    microversion = '2.37'
    sample_dir = 'servers'
    scenarios = [('v2_37', {'api_major_version': 'v2.1'})]

    def test_servers_post(self):
        self._post_server(use_common_server_api_samples=False)


class ServersSampleJson242Test(ServersSampleBase):
    microversion = '2.42'
    sample_dir = 'servers'
    scenarios = [('v2_42', {'api_major_version': 'v2.1'})]

    def test_servers_post(self):
        self._post_server(use_common_server_api_samples=False)


class ServersSampleJson247Test(ServersSampleJsonTest):
    microversion = '2.47'
    scenarios = [('v2_47', {'api_major_version': 'v2.1'})]
    use_common_server_post = False

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


class ServersSampleJson252Test(ServersSampleJsonTest):
    microversion = '2.52'
    scenarios = [('v2_52', {'api_major_version': 'v2.1'})]
    use_common_server_post = False


class ServersSampleJson263Test(ServersSampleBase):
    microversion = '2.63'
    scenarios = [('v2_63', {'api_major_version': 'v2.1'})]

    def setUp(self):
        super(ServersSampleJson263Test, self).setUp()
        self.common_subs = {
            'hostid': '[a-f0-9]+',
            'instance_name': 'instance-\d{8}',
            'hypervisor_hostname': r'[\w\.\-]+',
            'hostname': r'[\w\.\-]+',
            'access_ip_v4': '1.2.3.4',
            'access_ip_v6': '80fe::',
            'user_data': (self.user_data if six.PY2
                          else self.user_data.decode('utf-8')),
            'cdrive': '.*',
        }

    def test_servers_post(self):
        self._post_server(use_common_server_api_samples=False)

    def test_server_rebuild(self):
        uuid = self._post_server(use_common_server_api_samples=False)
        fakes.stub_out_key_pair_funcs(self)
        image = fake.get_valid_image_id()

        params = {
            'uuid': image,
            'name': 'foobar',
            'key_name': 'new-key',
            'description': 'description of foobar',
            'pass': 'seekr3t',
            'access_ip_v4': '1.2.3.4',
            'access_ip_v6': '80fe::',
        }

        resp = self._do_post('servers/%s/action' % uuid,
                             'server-action-rebuild', params)

        exp_resp = params.copy()
        del exp_resp['uuid']
        exp_resp['hostid'] = '[a-f0-9]+'

        self._verify_response('server-action-rebuild-resp',
                              exp_resp, resp, 202)

    def test_servers_details(self):
        uuid = self._post_server(use_common_server_api_samples=False)
        response = self._do_get('servers/detail?limit=1')
        subs = self.common_subs.copy()
        subs['id'] = uuid
        self._verify_response('servers-details-resp', subs, response, 200)

    def test_server_get(self):
        uuid = self._post_server(use_common_server_api_samples=False)
        response = self._do_get('servers/%s' % uuid)
        subs = self.common_subs.copy()
        subs['id'] = uuid
        self._verify_response('server-get-resp', subs, response, 200)

    def test_server_update(self):
        uuid = self._post_server(use_common_server_api_samples=False)
        subs = self.common_subs.copy()
        subs['id'] = uuid
        response = self._do_put('servers/%s' % uuid,
                                'server-update-req', subs)
        self._verify_response('server-update-resp', subs, response, 200)


class ServersUpdateSampleJsonTest(ServersSampleBase):

    def test_update_server(self):
        uuid = self._post_server()
        subs = {}
        subs['hostid'] = '[a-f0-9]+'
        subs['access_ip_v4'] = '1.2.3.4'
        subs['access_ip_v6'] = '80fe::'
        response = self._do_put('servers/%s' % uuid,
                                'server-update-req', subs)
        self._verify_response('server-update-resp', subs, response, 200)


class ServersUpdateSampleJson247Test(ServersUpdateSampleJsonTest):
    microversion = '2.47'
    scenarios = [('v2_47', {'api_major_version': 'v2.1'})]


class ServerSortKeysJsonTests(ServersSampleBase):
    sample_dir = 'servers-sort'

    def test_servers_list(self):
        self._post_server()
        response = self._do_get('servers?sort_key=display_name&sort_dir=asc')
        self._verify_response('server-sort-keys-list-resp', {}, response,
                              200)


class _ServersActionsJsonTestMixin(object):
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
            self.assertEqual("", response.text)
        return response


class ServersActionsJsonTest(ServersSampleBase, _ServersActionsJsonTestMixin):

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

    def _wait_for_active_server(self, uuid):
        """Wait 10 seconds for the server to be ACTIVE, else fail.

        :param uuid: The server id.
        :returns: The ACTIVE server.
        """
        server = self._do_get('servers/%s' % uuid,
                              return_json_body=True)['server']
        count = 0
        while server['status'] != 'ACTIVE' and count < 10:
            time.sleep(1)
            server = self._do_get('servers/%s' % uuid,
                                  return_json_body=True)['server']
            count += 1
        if server['status'] != 'ACTIVE':
            self.fail('Timed out waiting for server %s to be ACTIVE.' % uuid)
        return server

    def test_server_add_floating_ip(self):
        uuid = self._post_server()
        # Get the server details so we can find a fixed IP to use in the
        # addFloatingIp request.
        server = self._wait_for_active_server(uuid)
        addresses = server['addresses']
        # Find a fixed IP.
        fixed_address = None
        for network, ips in addresses.items():
            for ip in ips:
                if ip['OS-EXT-IPS:type'] == 'fixed':
                    fixed_address = ip['addr']
                    break
            if fixed_address:
                break
        if fixed_address is None:
            self.fail('Failed to find a fixed IP for server %s in addresses: '
                      '%s' % (uuid, addresses))
        subs = {
            "address": "10.10.10.10",
            "fixed_address": fixed_address
        }
        # This is gross, but we need to stub out the associate_floating_ip
        # call in the FloatingIPActionController since we don't have a real
        # networking service backing this up, just the fake nova-network stubs.
        self.stub_out('nova.network.api.API.associate_floating_ip',
                      lambda *a, **k: None)
        self._test_server_action(uuid, 'addFloatingIp',
                                 'server-action-addfloatingip-req', subs)

    def test_server_remove_floating_ip(self):
        server_uuid = self._post_server()
        self._wait_for_active_server(server_uuid)

        subs = {
            "address": "172.16.10.7"
        }

        self.stub_out('nova.network.api.API.get_floating_ip_by_address',
                      lambda *a, **k: {'fixed_ip_id':
                                       'a0c566f0-faab-406f-b77f-2b286dc6dd7e'})
        self.stub_out(
            'nova.network.api.API.get_instance_id_by_floating_address',
            lambda *a, **k: server_uuid)
        self.stub_out('nova.network.api.API.disassociate_floating_ip',
                      lambda *a, **k: None)

        self._test_server_action(server_uuid, 'removeFloatingIp',
                                 'server-action-removefloatingip-req', subs)


class ServersActionsJson219Test(ServersSampleBase):
    microversion = '2.19'
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


class ServersActionsJson226Test(ServersSampleBase):
    microversion = '2.26'
    scenarios = [('v2_26', {'api_major_version': 'v2.1'})]

    def test_server_rebuild(self):
        uuid = self._post_server()
        image = fake.get_valid_image_id()
        params = {
            'uuid': image,
            'access_ip_v4': '1.2.3.4',
            'access_ip_v6': '80fe::',
            'disk_config': 'AUTO',
            'hostid': '[a-f0-9]+',
            'name': 'foobar',
            'pass': 'seekr3t',
            'preserve_ephemeral': 'false',
            'description': 'description of foobar'
        }

        # Add 'tag1' and 'tag2' tags
        self._do_put('servers/%s/tags/tag1' % uuid)
        self._do_put('servers/%s/tags/tag2' % uuid)

        # Rebuild Action
        resp = self._do_post('servers/%s/action' % uuid,
                             'server-action-rebuild', params)

        subs = params.copy()
        del subs['uuid']
        self._verify_response('server-action-rebuild-resp', subs, resp, 202)


class ServersActionsJson254Test(ServersSampleBase):
    microversion = '2.54'
    sample_dir = 'servers'
    scenarios = [('v2_54', {'api_major_version': 'v2.1'})]

    def _create_server(self):
        return self._post_server()

    def test_server_rebuild(self):
        fakes.stub_out_key_pair_funcs(self)
        uuid = self._create_server()
        image = fake.get_valid_image_id()
        params = {
            'uuid': image,
            'name': 'foobar',
            'key_name': 'new-key',
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


class ServersActionsJson257Test(ServersActionsJson254Test):
    """Tests rebuilding a server with new user_data."""
    microversion = '2.57'
    scenarios = [('v2_57', {'api_major_version': 'v2.1'})]

    def _create_server(self):
        return self._post_server(use_common_server_api_samples=False)


class ServersCreateImageJsonTest(ServersSampleBase,
                                 _ServersActionsJsonTestMixin):
    """Tests the createImage server action API against 2.1."""
    def test_server_create_image(self):
        uuid = self._post_server()
        resp = self._test_server_action(uuid, 'createImage',
                                        'server-action-create-image',
                                        {'name': 'foo-image'})
        # we should have gotten a location header back
        self.assertIn('location', resp.headers)
        # we should not have gotten a body back
        self.assertEqual(0, len(resp.content))


class ServersCreateImageJsonTestv2_45(ServersCreateImageJsonTest):
    """Tests the createImage server action API against 2.45."""
    microversion = '2.45'
    scenarios = [('v2_45', {'api_major_version': 'v2.1'})]

    def test_server_create_image(self):
        uuid = self._post_server()
        resp = self._test_server_action(
            uuid, 'createImage', 'server-action-create-image',
            {'name': 'foo-image'}, 'server-action-create-image-resp')
        # assert that no location header was returned
        self.assertNotIn('location', resp.headers)


class ServerStartStopJsonTest(ServersSampleBase):

    def _test_server_action(self, uuid, action, req_tpl):
        response = self._do_post('servers/%s/action' % uuid,
                                 req_tpl,
                                 {'action': action})
        self.assertEqual(202, response.status_code)
        self.assertEqual("", response.text)

    def test_server_start(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'os-stop', 'server-action-stop')
        self._test_server_action(uuid, 'os-start', 'server-action-start')

    def test_server_stop(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'os-stop', 'server-action-stop')


class ServersSampleMultiStatusJsonTest(ServersSampleBase):

    def test_servers_list(self):
        uuid = self._post_server()
        response = self._do_get('servers?limit=1&status=active&status=error')
        subs = {'id': uuid, 'status': 'error'}
        self._verify_response('servers-list-status-resp', subs, response, 200)


class ServerTriggerCrashDumpJsonTest(ServersSampleBase):
    microversion = '2.17'
    scenarios = [('v2_17', {'api_major_version': 'v2.1'})]

    def test_trigger_crash_dump(self):
        uuid = self._post_server()

        response = self._do_post('servers/%s/action' % uuid,
                                 'server-action-trigger-crash-dump',
                                 {})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(response.text, "")
