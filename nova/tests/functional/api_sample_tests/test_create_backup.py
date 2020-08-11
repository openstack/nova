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

import mock

from nova.tests import fixtures
from nova.tests.functional.api_sample_tests import test_servers


class CreateBackupSamplesJsonTest(test_servers.ServersSampleBase):
    sample_dir = "os-create-backup"

    def setUp(self):
        """setUp Method for PauseServer api samples extension

        This method creates the server that will be used in each tests
        """
        super(CreateBackupSamplesJsonTest, self).setUp()
        self.uuid = self._post_server()

    @mock.patch.object(fixtures.GlanceFixture, 'detail', return_value=[])
    def test_post_backup_server(self, mock_method):
        # Get api samples to backup server request.
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'create-backup-req', {})
        self.assertEqual(202, response.status_code)
        # we should have gotten a location header back
        self.assertIn('location', response.headers)
        # we should not have gotten a body back
        self.assertEqual(0, len(response.content))


class CreateBackupSamplesJsonTestv2_45(CreateBackupSamplesJsonTest):
    """Tests the createBackup server action API with microversion 2.45."""
    microversion = '2.45'
    scenarios = [('v2_45', {'api_major_version': 'v2.1'})]

    def test_post_backup_server(self):
        # Get api samples to backup server request.
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'create-backup-req', {})
        self._verify_response('create-backup-resp', {}, response, 202)
        # assert that no location header was returned
        self.assertNotIn('location', response.headers)
