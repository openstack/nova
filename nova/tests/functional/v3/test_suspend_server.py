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

from nova.tests.functional.v3 import test_servers


class SuspendServerSamplesJsonTest(test_servers.ServersSampleBase):
    extension_name = "os-suspend-server"
    ctype = 'json'

    def setUp(self):
        """setUp Method for SuspendServer api samples extension

        This method creates the server that will be used in each tests
        """
        super(SuspendServerSamplesJsonTest, self).setUp()
        self.uuid = self._post_server()

    def test_post_suspend(self):
        # Get api samples to suspend server request.
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'server-suspend', {})
        self.assertEqual(response.status_code, 202)

    def test_post_resume(self):
        # Get api samples to server resume request.
        self.test_post_suspend()
        response = self._do_post('servers/%s/action' % self.uuid,
                                 'server-resume', {})
        self.assertEqual(response.status_code, 202)
