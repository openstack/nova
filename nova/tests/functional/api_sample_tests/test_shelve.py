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


import nova.conf
from nova import objects
from nova.tests.functional.api_sample_tests import test_servers
from oslo_utils.fixture import uuidsentinel
from unittest import mock

CONF = nova.conf.CONF

fake_aggregate = {
    'deleted': 0,
    'deleted_at': None,
    'created_at': None,
    'updated_at': None,
    'id': 123,
    'uuid': uuidsentinel.fake_aggregate,
    'name': 'us-west',
    'hosts': ['host01'],
    'metadetails': {'availability_zone': 'us-west'},
}


class ShelveJsonTest(test_servers.ServersSampleBase):
    # The 'os_compute_api:os-shelve:shelve_offload' policy is admin-only
    ADMIN_API = True
    sample_dir = "os-shelve"

    def setUp(self):
        super(ShelveJsonTest, self).setUp()
        # Don't offload instance, so we can test the offload call.
        CONF.set_override('shelved_offload_time', -1)

    def _test_server_action(self, uuid, template, action, subs=None):
        subs = subs or {}
        subs.update({'action': action})
        response = self._do_post('servers/%s/action' % uuid,
                                 template, subs)
        self.assertEqual(202, response.status_code)
        self.assertEqual("", response.text)

    def test_shelve(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'os-shelve', 'shelve')

    def test_shelve_offload(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'os-shelve', 'shelve')
        self._test_server_action(uuid, 'os-shelve-offload', 'shelveOffload')

    def test_unshelve(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'os-shelve', 'shelve')
        self._test_server_action(uuid, 'os-unshelve', 'unshelve')


class UnshelveJson277Test(ShelveJsonTest):
    ADMIN_API = False
    sample_dir = "os-shelve"
    microversion = '2.77'
    scenarios = [('v2_77', {'api_major_version': 'v2.1'})]

    def setUp(self):
        super(UnshelveJson277Test, self).setUp()
        # Almost all next tests require the instance to be shelve offloaded.
        # So shelve offload the instance and skip the shelve_offload_test
        # below.
        CONF.set_override('shelved_offload_time', 0)

    def test_shelve_offload(self):
        # Skip this test as the instance is already shelve offloaded.
        pass

    def test_unshelve_with_az(self):
        uuid = self._post_server()
        self._test_server_action(uuid, 'os-shelve', 'shelve')
        self._test_server_action(
            uuid,
            'os-unshelve-az',
            'unshelve',
            subs={"availability_zone": "us-west"}
        )


class UnshelveJson291Test(UnshelveJson277Test):
    ADMIN_API = True
    sample_dir = "os-shelve"
    microversion = '2.91'
    scenarios = [('v2_91', {'api_major_version': 'v2.1'})]

    def _test_server_action_invalid(
            self, uuid, template, action, subs=None, msg=None):
        subs = subs or {}
        subs.update({'action': action})
        response = self._do_post('servers/%s/action' % uuid,
                                 template, subs)
        self.assertEqual(400, response.status_code)
        self.assertIn(msg, response.text)

    def test_unshelve_with_non_valid_host(self):
        """Ensure an exception rise if host is invalid and
        a http 400 error
        """
        uuid = self._post_server()
        self._test_server_action(uuid, 'os-shelve', 'shelve')
        self._test_server_action_invalid(
            uuid, 'os-unshelve-host',
            'unshelve',
            subs={'host': 'host01'},
            msg='Compute host host01 could not be found.')

    @mock.patch('nova.objects.aggregate._get_by_host_from_db')
    @mock.patch('nova.objects.ComputeNodeList.get_all_by_host')
    def test_unshelve_with_valid_host(
            self, compute_node_get_all_by_host, mock_api_get_by_host):
        """Ensure we can unshelve to a host
        """
        # Put compute in the correct az
        mock_api_get_by_host.return_value = [fake_aggregate]

        uuid = self._post_server()
        self._test_server_action(uuid, 'os-shelve', 'shelve')
        fake_computes = objects.ComputeNodeList(
            objects=[
                objects.ComputeNode(
                    host='host01',
                    uuid=uuidsentinel.host1,
                    hypervisor_hostname='host01')
            ]
        )
        compute_node_get_all_by_host.return_value = fake_computes

        self._test_server_action(
            uuid,
            'os-unshelve-host',
            'unshelve',
            subs={'host': 'host01'}
        )

    @mock.patch('nova.objects.aggregate._get_by_host_from_db')
    @mock.patch('nova.objects.ComputeNodeList.get_all_by_host')
    def test_unshelve_with_az_and_host(
            self, compute_node_get_all_by_host, mock_api_get_by_host):
        """Ensure we can unshelve to a host and az
        """
        # Put compute in the correct az
        mock_api_get_by_host.return_value = [fake_aggregate]

        uuid = self._post_server()
        self._test_server_action(uuid, 'os-shelve', 'shelve')
        fake_computes = objects.ComputeNodeList(
            objects=[
                objects.ComputeNode(
                    host='host01',
                    uuid=uuidsentinel.host1,
                    hypervisor_hostname='host01')
            ]
        )
        compute_node_get_all_by_host.return_value = fake_computes

        self._test_server_action(
            uuid,
            'os-unshelve-host',
            'unshelve',
            subs={'host': 'host01', 'availability_zone': 'us-west'},
        )

    @mock.patch('nova.objects.aggregate._get_by_host_from_db')
    @mock.patch('nova.objects.ComputeNodeList.get_all_by_host')
    def test_unshelve_with_unpin_az_and_host(
            self, compute_node_get_all_by_host, mock_api_get_by_host):
        """Ensure we can unshelve to a host and az
        """
        # Put compute in the correct az
        mock_api_get_by_host.return_value = [fake_aggregate]

        uuid = self._post_server()
        self._test_server_action(uuid, 'os-shelve', 'shelve')
        fake_computes = objects.ComputeNodeList(
            objects=[
                objects.ComputeNode(
                    host='host01',
                    uuid=uuidsentinel.host1,
                    hypervisor_hostname='host01')
            ]
        )
        compute_node_get_all_by_host.return_value = fake_computes

        self._test_server_action(
            uuid,
            'os-unshelve-host-and-unpin-az',
            'unshelve',
            subs={'host': 'host01'},
        )

    @mock.patch('nova.objects.aggregate._get_by_host_from_db')
    @mock.patch('nova.objects.ComputeNodeList.get_all_by_host')
    def test_unshelve_with_unpin_az(
            self, compute_node_get_all_by_host, mock_api_get_by_host):
        """Ensure we can unpin an az
        """
        # Put compute in the correct az
        mock_api_get_by_host.return_value = [fake_aggregate]

        uuid = self._post_server()
        self._test_server_action(uuid, 'os-shelve', 'shelve')
        fake_computes = objects.ComputeNodeList(
            objects=[
                objects.ComputeNode(
                    host='host01',
                    uuid=uuidsentinel.host1,
                    hypervisor_hostname='host01')
            ]
        )
        compute_node_get_all_by_host.return_value = fake_computes

        self._test_server_action(
            uuid,
            'os-unshelve-unpin-az',
            'unshelve',
            subs={'host': 'host01'},
        )


class UnshelveJson291NonAdminTest(UnshelveJson291Test):
    # Use non admin api credentials.
    ADMIN_API = False
    sample_dir = "os-shelve"
    microversion = '2.91'
    scenarios = [('v2_91', {'api_major_version': 'v2.1'})]

    def _test_server_action_invalid(self, uuid, template, action, subs=None):
        subs = subs or {}
        subs.update({'action': action})
        response = self._do_post('servers/%s/action' % uuid,
                                 template, subs)
        self.assertEqual(403, response.status_code)
        self.assertIn(
            "Policy doesn\'t allow os_compute_api:os-shelve:unshelve_to_host" +
            " to be performed.", response.text)

    def _test_server_action(self, uuid, template, action, subs=None):
        subs = subs or {}
        subs.update({'action': action})
        response = self._do_post('servers/%s/action' % uuid,
                                 template, subs)
        self.assertEqual(202, response.status_code)
        self.assertEqual('', response.text)

    def test_unshelve_with_non_valid_host(self):
        """Ensure an exception rise if user is not admin.
        a http 403 error
        """
        uuid = self._post_server()
        self._test_server_action(uuid, 'os-shelve', 'shelve')
        self._test_server_action_invalid(
            uuid,
            'os-unshelve-host',
            'unshelve',
            subs={'host': 'host01'}
        )

    @mock.patch('nova.objects.aggregate._get_by_host_from_db')
    @mock.patch('nova.objects.ComputeNodeList.get_all_by_host')
    def test_unshelve_with_unpin_az_and_host(
            self, compute_node_get_all_by_host, mock_api_get_by_host):
        # Put compute in the correct az
        mock_api_get_by_host.return_value = [fake_aggregate]

        uuid = self._post_server()
        self._test_server_action(uuid, 'os-shelve', 'shelve')
        fake_computes = objects.ComputeNodeList(
            objects=[
                objects.ComputeNode(
                    host='host01',
                    uuid=uuidsentinel.host1,
                    hypervisor_hostname='host01')
            ]
        )
        compute_node_get_all_by_host.return_value = fake_computes

        self._test_server_action_invalid(
            uuid,
            'os-unshelve-host-and-unpin-az',
            'unshelve',
            subs={'host': 'host01'},
        )

    @mock.patch('nova.objects.aggregate._get_by_host_from_db')
    @mock.patch('nova.objects.ComputeNodeList.get_all_by_host')
    def test_unshelve_with_valid_host(
            self, compute_node_get_all_by_host, mock_api_get_by_host):
        # Put compute in the correct az
        mock_api_get_by_host.return_value = [fake_aggregate]

        uuid = self._post_server()
        self._test_server_action(uuid, 'os-shelve', 'shelve')
        fake_computes = objects.ComputeNodeList(
            objects=[
                objects.ComputeNode(
                    host='host01',
                    uuid=uuidsentinel.host1,
                    hypervisor_hostname='host01')
            ]
        )
        compute_node_get_all_by_host.return_value = fake_computes

        self._test_server_action_invalid(
            uuid,
            'os-unshelve-host',
            'unshelve',
            subs={'host': 'host01'}
        )

    @mock.patch('nova.objects.aggregate._get_by_host_from_db')
    @mock.patch('nova.objects.ComputeNodeList.get_all_by_host')
    def test_unshelve_with_az_and_host(
            self, compute_node_get_all_by_host, mock_api_get_by_host):
        """Ensure we can unshelve to a host and az
        """
        # Put compute in the correct az
        mock_api_get_by_host.return_value = [fake_aggregate]

        uuid = self._post_server()
        self._test_server_action(uuid, 'os-shelve', 'shelve')
        fake_computes = objects.ComputeNodeList(
            objects=[
                objects.ComputeNode(
                    host='host01',
                    uuid=uuidsentinel.host1,
                    hypervisor_hostname='host01')
            ]
        )
        compute_node_get_all_by_host.return_value = fake_computes

        self._test_server_action_invalid(
            uuid,
            'os-unshelve-host',
            'unshelve',
            subs={'host': 'host01', 'availability_zone': 'us-west'},
        )
