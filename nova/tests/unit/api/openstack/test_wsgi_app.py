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

import tempfile
from unittest import mock

import fixtures
from oslo_config import fixture as config_fixture
from oslotest import base

from nova.api.openstack import wsgi_app
from nova import exception
from nova import test
from nova.tests import fixtures as nova_fixtures


class WSGIAppTest(base.BaseTestCase):

    _paste_config = """
[app:nova-api]
use = egg:Paste#static
document_root = /tmp
    """

    def setUp(self):
        # Ensure BaseTestCase's ConfigureLogging fixture is disabled since
        # we're using our own (StandardLogging).
        with fixtures.EnvironmentVariable('OS_LOG_CAPTURE', '0'):
            super(WSGIAppTest, self).setUp()
        self.stdlog = self.useFixture(nova_fixtures.StandardLogging())
        self.conf = tempfile.NamedTemporaryFile(mode='w+t')
        self.conf.write(self._paste_config.lstrip())
        self.conf.seek(0)
        self.conf.flush()
        self.addCleanup(self.conf.close)
        # Use of this fixture takes care of cleaning up config settings for
        # subsequent tests.
        self.useFixture(config_fixture.Config())

    @mock.patch('sys.argv', return_value=mock.sentinel.argv)
    @mock.patch('nova.db.api.api.configure')
    @mock.patch('nova.db.main.api.configure')
    @mock.patch('nova.api.openstack.wsgi_app._setup_service')
    @mock.patch('nova.api.openstack.wsgi_app._get_config_files')
    def test_init_application_called_twice(
        self, mock_get_files, mock_setup, mock_main_db_configure,
        mock_api_db_configure, mock_argv,
    ):
        """Test that init_application can tolerate being called twice in a
        single python interpreter instance.

        When nova-api is run via mod_wsgi, if any exception is raised during
        init_application, mod_wsgi will re-run the WSGI script without
        restarting the daemon process even when configured for Daemon Mode.

        We access the database as part of init_application, so if nova-api
        starts up before the database is up, we'll get, for example, a
        DBConnectionError raised during init_application and our WSGI script
        will get reloaded/re-run by mod_wsgi.
        """
        mock_get_files.return_value = [self.conf.name]
        mock_setup.side_effect = [test.TestingException, None]
        # We need to mock the global database configure() methods, else we will
        # be affected by global database state altered by other tests that ran
        # before this test, causing this test to fail with
        # oslo_db.sqlalchemy.enginefacade.AlreadyStartedError. We can instead
        # mock the method to raise an exception if it's called a second time in
        # this test to simulate the fact that the database does not tolerate
        # re-init [after a database query has been made].
        mock_main_db_configure.side_effect = [None, test.TestingException]
        mock_api_db_configure.side_effect = [None, test.TestingException]
        # Run init_application the first time, simulating an exception being
        # raised during it.
        self.assertRaises(test.TestingException, wsgi_app.init_application,
                          'nova-api')
        # Now run init_application a second time, it should succeed since no
        # exception is being raised (the init of global data should not be
        # re-attempted).
        wsgi_app.init_application('nova-api')
        self.assertIn('Global data already initialized, not re-initializing.',
                      self.stdlog.logger.output)

    @mock.patch('nova.objects.Service.get_by_host_and_binary')
    @mock.patch('nova.utils.raise_if_old_compute')
    def test_setup_service_version_workaround(self, mock_check_old, mock_get):
        mock_check_old.side_effect = exception.TooOldComputeService(
            oldest_supported_version='2',
            scope='scope',
            min_service_level=2,
            oldest_supported_service=1)

        self.assertRaises(exception.TooOldComputeService,
                          wsgi_app._setup_service, 'myhost', 'api')
        wsgi_app.CONF.set_override(
            'disable_compute_service_check_for_ffu', True,
            group='workarounds')
        wsgi_app._setup_service('myhost', 'api')

    def test__get_config_files_empty_env(self):
        env = {}
        result = wsgi_app._get_config_files(env)
        expected = ['/etc/nova/api-paste.ini', '/etc/nova/nova.conf']
        self.assertEqual(result, expected)

    def test__get_config_files_with_env(self):
        env = {
            "OS_NOVA_CONFIG_DIR": "/nova",
            "OS_NOVA_CONFIG_FILES": "api.conf",
        }
        result = wsgi_app._get_config_files(env)
        expected = ['/nova/api.conf']
        self.assertEqual(result, expected)
