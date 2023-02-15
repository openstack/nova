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

from unittest import mock

from nova import exception
from nova import test
from nova.tests import fixtures
from nova.virt.libvirt.cpu import core


class TestCore(test.NoDBTestCase):

    @mock.patch.object(core.filesystem, 'read_sys')
    @mock.patch.object(core.hardware, 'parse_cpu_spec')
    def test_get_available_cores(self, mock_parse_cpu_spec, mock_read_sys):
        mock_read_sys.return_value = '1-2'
        mock_parse_cpu_spec.return_value = set([1, 2])
        self.assertEqual(set([1, 2]), core.get_available_cores())
        mock_read_sys.assert_called_once_with(core.AVAILABLE_PATH)
        mock_parse_cpu_spec.assert_called_once_with('1-2')

    @mock.patch.object(core.filesystem, 'read_sys')
    @mock.patch.object(core.hardware, 'parse_cpu_spec')
    def test_get_available_cores_none(
            self, mock_parse_cpu_spec, mock_read_sys):
        mock_read_sys.return_value = ''
        self.assertEqual(set(), core.get_available_cores())
        mock_parse_cpu_spec.assert_not_called()

    @mock.patch.object(core, 'get_available_cores')
    def test_exists(self, mock_get_available_cores):
        mock_get_available_cores.return_value = set([1])
        self.assertTrue(core.exists(1))
        mock_get_available_cores.assert_called_once_with()
        self.assertFalse(core.exists(2))

    @mock.patch.object(
            core, 'CPU_PATH_TEMPLATE',
            new_callable=mock.PropertyMock(return_value='/sys/blah%(core)s'))
    @mock.patch.object(core, 'exists')
    def test_gen_cpu_path(self, mock_exists, mock_cpu_path):
        mock_exists.return_value = True
        self.assertEqual('/sys/blah1', core.gen_cpu_path(1))
        mock_exists.assert_called_once_with(1)

    @mock.patch.object(core, 'exists')
    def test_gen_cpu_path_raises(self, mock_exists):
        mock_exists.return_value = False
        self.assertRaises(ValueError, core.gen_cpu_path, 1)
        self.assertIn('Unable to access CPU: 1', self.stdlog.logger.output)


class TestCoreHelpers(test.NoDBTestCase):

    def setUp(self):
        super(TestCoreHelpers, self).setUp()
        self.useFixture(fixtures.PrivsepFixture())
        _p1 = mock.patch.object(core, 'exists', return_value=True)
        self.mock_exists = _p1.start()
        self.addCleanup(_p1.stop)

        _p2 = mock.patch.object(core, 'gen_cpu_path',
                                side_effect=lambda x: '/fakesys/blah%s' % x)
        self.mock_gen_cpu_path = _p2.start()
        self.addCleanup(_p2.stop)

    @mock.patch.object(core.filesystem, 'read_sys')
    def test_get_online(self, mock_read_sys):
        mock_read_sys.return_value = '1'
        self.assertTrue(core.get_online(1))
        mock_read_sys.assert_called_once_with('/fakesys/blah1/online')

    @mock.patch.object(core.filesystem, 'read_sys')
    def test_get_online_not_exists(self, mock_read_sys):
        mock_read_sys.side_effect = exception.FileNotFound(file_path='foo')
        self.assertTrue(core.get_online(1))
        mock_read_sys.assert_called_once_with('/fakesys/blah1/online')

    @mock.patch.object(core.filesystem, 'write_sys')
    @mock.patch.object(core, 'get_online')
    def test_set_online(self, mock_get_online, mock_write_sys):
        mock_get_online.return_value = True
        self.assertTrue(core.set_online(1))
        mock_write_sys.assert_called_once_with('/fakesys/blah1/online',
                                               data='1')
        mock_get_online.assert_called_once_with(1)

    @mock.patch.object(core.filesystem, 'write_sys')
    @mock.patch.object(core, 'get_online')
    def test_set_offline(self, mock_get_online, mock_write_sys):
        mock_get_online.return_value = False
        self.assertTrue(core.set_offline(1))
        mock_write_sys.assert_called_once_with('/fakesys/blah1/online',
                                               data='0')
        mock_get_online.assert_called_once_with(1)

    @mock.patch.object(core.filesystem, 'read_sys')
    def test_get_governor(self, mock_read_sys):
        mock_read_sys.return_value = 'fake_gov'
        self.assertEqual('fake_gov', core.get_governor(1))
        mock_read_sys.assert_called_once_with(
            '/fakesys/blah1/cpufreq/scaling_governor')

    @mock.patch.object(core, 'get_governor')
    @mock.patch.object(core.filesystem, 'write_sys')
    def test_set_governor(self, mock_write_sys, mock_get_governor):
        mock_get_governor.return_value = 'fake_gov'
        self.assertEqual('fake_gov',
                         core.set_governor(1, 'fake_gov'))
        mock_write_sys.assert_called_once_with(
            '/fakesys/blah1/cpufreq/scaling_governor', data='fake_gov')
        mock_get_governor.assert_called_once_with(1)
