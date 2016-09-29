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

from nova.tests.functional.api_sample_tests import test_servers


class LockServerSamplesJsonTest(test_servers.ServersSampleBase):
    sample_dir = "os-lock-server"

    def setUp(self):
        """setUp Method for LockServer api samples extension

        This method creates the server that will be used in each tests
        """
        super(LockServerSamplesJsonTest, self).setUp()
        self.uuid = self._post_server()

    def test_post_lock_server(self):
        # Get api samples to lock server request.
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'lock-server', {})
        self.assertEqual(202, response.status_code)

    def test_post_unlock_server(self):
        # Get api samples to unlock server request.
        self.test_post_lock_server()
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'unlock-server', {})
        self.assertEqual(202, response.status_code)
