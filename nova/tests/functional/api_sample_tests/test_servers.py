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

from oslo_utils import fixture as utils_fixture
from oslo_utils import timeutils
import six

from nova.api.openstack import api_version_request as avr
import nova.conf
from nova.tests import fixtures as nova_fixtures
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

    def _get_request_name(self, use_common, sample_name=None):
        if not use_common:
            return sample_name or 'server-create-req'

        api_version = self.microversion or '2.1'
        for min, max, name in self.common_req_names:
            if avr.APIVersionRequest(api_version).matches(
                    avr.APIVersionRequest(min), avr.APIVersionRequest(max)):
                return name

    def _post_server(self, use_common_server_api_samples=True, name=None,
                     extra_subs=None, sample_name=None):
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
        # If the template is requesting an explicit availability zone and
        # the test is setup to have AZs, use the first one in the list which
        # should default to "us-west".
        if self.availability_zones:
            subs['availability_zone'] = self.availability_zones[0]
        if extra_subs:
            subs.update(extra_subs)

        orig_value = self.__class__._use_common_server_api_samples
        try:
            self.__class__._use_common_server_api_samples = (
                                        use_common_server_api_samples)
            # If using common samples, we could only put samples under
            # api_samples/servers. We will put a lot of samples when we
            # have more and more microversions.
            # Callers can specify the sample_name param so that we can add
            # samples into api_samples/servers/v2.xx.
            response = self._do_post('servers', self._get_request_name(
                use_common_server_api_samples, sample_name), subs)
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
        subs['instance_name'] = r'instance-\d{8}'
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
        subs['instance_name'] = r'instance-\d{8}'
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
            'instance_name': r'instance-\d{8}',
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


class ServersSampleJson266Test(ServersSampleBase):
    microversion = '2.66'
    scenarios = [('v2_66', {'api_major_version': 'v2.1'})]

    def setUp(self):
        super(ServersSampleJson266Test, self).setUp()
        self.common_subs = {
            'hostid': '[a-f0-9]+',
            'instance_name': r'instance-\d{8}',
            'hypervisor_hostname': r'[\w\.\-]+',
            'hostname': r'[\w\.\-]+',
            'access_ip_v4': '1.2.3.4',
            'access_ip_v6': '80fe::',
            'user_data': (self.user_data if six.PY2
                          else self.user_data.decode('utf-8')),
            'cdrive': '.*',
        }

    def test_get_servers_list_with_changes_before(self):
        uuid = self._post_server(use_common_server_api_samples=False)
        current_time = timeutils.parse_isotime(timeutils.utcnow().isoformat())
        response = self._do_get(
            'servers?changes-before=%s' % timeutils.normalize_time(
                current_time))
        subs = self.common_subs.copy()
        subs['id'] = uuid
        self._verify_response(
            'servers-list-with-changes-before', subs, response, 200)

    def test_get_servers_detail_with_changes_before(self):
        uuid = self._post_server(use_common_server_api_samples=False)
        current_time = timeutils.parse_isotime(timeutils.utcnow().isoformat())
        response = self._do_get(
            'servers/detail?changes-before=%s' % timeutils.normalize_time(
                current_time))
        subs = self.common_subs.copy()
        subs['id'] = uuid
        self._verify_response(
            'servers-details-with-changes-before', subs, response, 200)


class ServersSampleJson267Test(ServersSampleBase):
    microversion = '2.67'
    scenarios = [('v2_67', {'api_major_version': 'v2.1'})]

    def setUp(self):
        super(ServersSampleJson267Test, self).setUp()
        self.useFixture(nova_fixtures.CinderFixture(self))

    def test_servers_post(self):
        return self._post_server(use_common_server_api_samples=False)


class ServersSampleJson269Test(ServersSampleBase):
    microversion = '2.69'
    scenarios = [('v2_69', {'api_major_version': 'v2.1'})]

    def setUp(self):
        super(ServersSampleJson269Test, self).setUp()

        def _fake_instancemapping_get_by_cell_and_project(*args, **kwargs):
            # global cell based on which rest of the functions are stubbed out
            cell_fixture = nova_fixtures.SingleCellSimple()
            return [{
                'id': 1,
                'updated_at': None,
                'created_at': None,
                'instance_uuid': utils_fixture.uuidsentinel.inst,
                'cell_id': 1,
                'project_id': "6f70656e737461636b20342065766572",
                'cell_mapping': cell_fixture._fake_cell_list()[0],
                'queued_for_delete': False
            }]

        self.stub_out('nova.objects.InstanceMappingList.'
            '_get_not_deleted_by_cell_and_project_from_db',
            _fake_instancemapping_get_by_cell_and_project)

    def test_servers_list_from_down_cells(self):
        uuid = self._post_server(use_common_server_api_samples=False)
        with nova_fixtures.DownCellFixture():
            response = self._do_get('servers')
        subs = {'id': uuid}
        self._verify_response('servers-list-resp', subs, response, 200)

    def test_servers_details_from_down_cells(self):
        uuid = self._post_server(use_common_server_api_samples=False)
        with nova_fixtures.DownCellFixture():
            response = self._do_get('servers/detail')
        subs = {'id': uuid}
        self._verify_response('servers-details-resp', subs, response, 200)

    def test_server_get_from_down_cells(self):
        uuid = self._post_server(use_common_server_api_samples=False)
        with nova_fixtures.DownCellFixture():
            response = self._do_get('servers/%s' % uuid)
        subs = {'id': uuid}
        self._verify_response('server-get-resp', subs, response, 200)


class ServersSampleJson271Test(ServersSampleBase):
    microversion = '2.71'
    scenarios = [('v2_71', {'api_major_version': 'v2.1'})]

    def setUp(self):
        super(ServersSampleJson271Test, self).setUp()
        self.common_subs = {
            'hostid': '[a-f0-9]+',
            'instance_name': r'instance-\d{8}',
            'hypervisor_hostname': r'[\w\.\-]+',
            'hostname': r'[\w\.\-]+',
            'access_ip_v4': '1.2.3.4',
            'access_ip_v6': '80fe::',
            'user_data': (self.user_data if six.PY2
                          else self.user_data.decode('utf-8')),
            'cdrive': '.*',
        }

        # create server group
        subs = {'name': 'test'}
        response = self._do_post('os-server-groups',
                                 'server-groups-post-req', subs)
        self.sg_uuid = self._verify_response('server-groups-post-resp',
                                              subs, response, 200)

    def _test_servers_post(self):
        return self._post_server(
            use_common_server_api_samples=False,
            extra_subs={'sg_uuid': self.sg_uuid})

    def test_servers_get_with_server_group(self):
        uuid = self._test_servers_post()
        response = self._do_get('servers/%s' % uuid)
        subs = self.common_subs.copy()
        subs['id'] = uuid
        self._verify_response('server-get-resp', subs, response, 200)

    def test_servers_update_with_server_groups(self):
        uuid = self._test_servers_post()
        subs = self.common_subs.copy()
        subs['id'] = uuid
        response = self._do_put('servers/%s' % uuid,
                                'server-update-req', subs)
        self._verify_response('server-update-resp', subs, response, 200)

    def test_servers_rebuild_with_server_groups(self):
        uuid = self._test_servers_post()
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
        subs = self.common_subs.copy()
        subs.update(params)
        subs['id'] = uuid
        del subs['uuid']
        self._verify_response('server-action-rebuild-resp', subs, resp, 202)

    def test_server_get_from_down_cells(self):
        def _fake_instancemapping_get_by_cell_and_project(*args, **kwargs):
            # global cell based on which rest of the functions are stubbed out
            cell_fixture = nova_fixtures.SingleCellSimple()
            return [{
                'id': 1,
                'updated_at': None,
                'created_at': None,
                'instance_uuid': utils_fixture.uuidsentinel.inst,
                'cell_id': 1,
                'project_id': "6f70656e737461636b20342065766572",
                'cell_mapping': cell_fixture._fake_cell_list()[0],
                'queued_for_delete': False
            }]

        self.stub_out('nova.objects.InstanceMappingList.'
            '_get_not_deleted_by_cell_and_project_from_db',
            _fake_instancemapping_get_by_cell_and_project)

        uuid = self._test_servers_post()
        with nova_fixtures.DownCellFixture():
            response = self._do_get('servers/%s' % uuid)
        subs = {'id': uuid}
        self._verify_response('server-get-down-cell-resp',
                              subs, response, 200)


class ServersSampleJson273Test(ServersSampleBase):
    microversion = '2.73'
    scenarios = [('v2_73', {'api_major_version': 'v2.1'})]

    def _post_server_and_lock(self):
        uuid = self._post_server(use_common_server_api_samples=False)
        reason = "I don't want to work"
        self._do_post('servers/%s/action' % uuid,
            'lock-server-with-reason',
            {"locked_reason": reason})
        return uuid

    def test_servers_details_with_locked_reason(self):
        uuid = self._post_server_and_lock()
        response = self._do_get('servers/detail')
        subs = {'id': uuid}
        self._verify_response('servers-details-resp', subs, response, 200)

    def test_server_get_with_locked_reason(self):
        uuid = self._post_server_and_lock()
        response = self._do_get('servers/%s' % uuid)
        subs = {'id': uuid}
        self._verify_response('server-get-resp', subs, response, 200)

    def test_server_rebuild_with_empty_locked_reason(self):
        uuid = self._post_server(use_common_server_api_samples=False)
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

    def test_update_server_with_empty_locked_reason(self):
        uuid = self._post_server(use_common_server_api_samples=False)
        subs = {}
        subs['hostid'] = '[a-f0-9]+'
        subs['access_ip_v4'] = '1.2.3.4'
        subs['access_ip_v6'] = '80fe::'
        response = self._do_put('servers/%s' % uuid,
                                'server-update-req', subs)
        self._verify_response('server-update-resp', subs, response, 200)


class ServersSampleJson274Test(ServersSampleBase):
    """Supporting host and/or hypervisor_hostname is an admin API
    to create servers.
    """
    ADMIN_API = True
    SUPPORTS_CELLS = True
    microversion = '2.74'
    scenarios = [('v2_74', {'api_major_version': 'v2.1'})]
    # Do not put an availability_zone in the API sample request since it would
    # be confusing with the requested host/hypervisor_hostname and forced
    # host/node zone:host:node case.
    availability_zones = []

    def _setup_compute_service(self):
        return self.start_service('compute', host='openstack-node-01')

    def setUp(self):
        super(ServersSampleJson274Test, self).setUp()

    def test_servers_post_with_only_host(self):
        self._post_server(use_common_server_api_samples=False,
                          sample_name='server-create-req-with-only-host')

    def test_servers_post_with_only_node(self):
        self._post_server(use_common_server_api_samples=False,
                          sample_name='server-create-req-with-only-node')

    def test_servers_post_with_host_and_node(self):
        self._post_server(use_common_server_api_samples=False,
                          sample_name='server-create-req-with-host-and-node')


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


class ServersSampleJson275Test(ServersUpdateSampleJsonTest):
    microversion = '2.75'
    scenarios = [('v2_75', {'api_major_version': 'v2.1'})]

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
    SUPPORTS_CELLS = True

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
        # networking service backing this up, just the fake neutron stubs.
        self.stub_out('nova.network.neutron.API.associate_floating_ip',
                      lambda *a, **k: None)
        self._test_server_action(uuid, 'addFloatingIp',
                                 'server-action-addfloatingip-req', subs)

    def test_server_remove_floating_ip(self):
        server_uuid = self._post_server()
        self._wait_for_active_server(server_uuid)

        subs = {
            "address": "172.16.10.7"
        }

        self.stub_out(
            'nova.network.neutron.API.get_floating_ip_by_address',
            lambda *a, **k: {
                'port_id': 'a0c566f0-faab-406f-b77f-2b286dc6dd7e'})
        self.stub_out(
            'nova.network.neutron.API.'
            'get_instance_id_by_floating_address',
            lambda *a, **k: server_uuid)
        self.stub_out(
            'nova.network.neutron.API.disassociate_floating_ip',
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
