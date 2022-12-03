# Copyright (C) 2022 Red Hat, Inc
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


from nova.tests import fixtures as nova_fixtures
from nova.tests.functional.api import client
from nova.tests.functional import integrated_helpers
from nova.tests.functional.libvirt import base
from unittest import mock


class LibvirtDriverTests(
    base.ServersTestBase,
    integrated_helpers.InstanceHelperMixin
):
    api_major_version = 'v2.1'
    microversion = 'latest'

    def setUp(self):
        super(LibvirtDriverTests, self).setUp()
        self.cinder = self.useFixture(nova_fixtures.CinderFixture(self))
        self.start_compute()

    def _create_server_with_block_device(self):
        server_request = self._build_server(
            networks=[],
        )
        # removing imageRef is required as we want
        # to boot from volume
        server_request.pop('imageRef')
        server_request['block_device_mapping_v2'] = [{
            'boot_index': 0,
            'source_type': 'volume',
            'uuid': nova_fixtures.CinderFixture.IMAGE_BACKED_VOL_QUIESCE,
            'destination_type': 'volume'}]

        server = self.api.post_server({
            'server': server_request,
        })
        self._wait_for_state_change(server, 'ACTIVE')
        return server

    def test_snapshot_quiesce_fail(self):
        server = self._create_server_with_block_device()
        with mock.patch.object(
            nova_fixtures.libvirt.Domain, 'fsFreeze'
        ) as mock_obj:
            ex = nova_fixtures.libvirt.libvirtError("Error")
            ex.err = (nova_fixtures.libvirt.VIR_ERR_AGENT_UNRESPONSIVE,)

            mock_obj.side_effect = ex
            excep = self.assertRaises(
                    client.OpenStackApiException,
                    self._snapshot_server, server, "snapshot-1"
                )
            self.assertEqual(409, excep.response.status_code)
