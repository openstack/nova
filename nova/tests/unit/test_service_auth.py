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

from keystoneauth1 import loading as ks_loading
from keystoneauth1 import service_token
import mock

from nova import context
from nova import service_auth
from nova import test


class ServiceAuthTestCase(test.NoDBTestCase):

    def setUp(self):
        super(ServiceAuthTestCase, self).setUp()
        self.ctx = context.RequestContext('fake', 'fake')
        self.addCleanup(service_auth.reset_globals)

    @mock.patch.object(ks_loading, 'load_auth_from_conf_options')
    def test_get_auth_plugin_no_wraps(self, mock_load):
        context = mock.MagicMock()
        context.get_auth_plugin.return_value = "fake"

        result = service_auth.get_auth_plugin(context)

        self.assertEqual("fake", result)
        mock_load.assert_not_called()

    @mock.patch.object(ks_loading, 'load_auth_from_conf_options')
    def test_get_auth_plugin_wraps(self, mock_load):
        self.flags(send_service_user_token=True, group='service_user')

        result = service_auth.get_auth_plugin(self.ctx)

        self.assertIsInstance(result, service_token.ServiceTokenAuthWrapper)

    @mock.patch.object(ks_loading, 'load_auth_from_conf_options',
                       return_value=None)
    def test_get_auth_plugin_wraps_bad_config(self, mock_load):
        """Tests the case that send_service_user_token is True but there
        is some misconfiguration with the [service_user] section which makes
        KSA return None for the service user auth.
        """
        self.flags(send_service_user_token=True, group='service_user')
        result = service_auth.get_auth_plugin(self.ctx)
        self.assertEqual(1, mock_load.call_count)
        self.assertNotIsInstance(result, service_token.ServiceTokenAuthWrapper)
