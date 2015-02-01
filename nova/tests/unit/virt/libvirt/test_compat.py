#  Licensed under the Apache License, Version 2.0 (the "License"); you may
#  not use this file except in compliance with the License. You may obtain
#  a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#  WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#  License for the specific language governing permissions and limitations
#  under the License.

import mock

from nova.compute import power_state
from nova import test
from nova.tests.unit.virt.libvirt import fakelibvirt
from nova.virt.libvirt import compat
from nova.virt.libvirt import host


class CompatTestCase(test.NoDBTestCase):

    def setUp(self):
        super(CompatTestCase, self).setUp()
        self.useFixture(fakelibvirt.FakeLibvirtFixture())

    @mock.patch.object(host.Host, 'has_min_version')
    def test_get_domain_info(self, mock_has_min_version):
        test_host = host.Host("qemu:///system")
        domain = mock.MagicMock()
        expected = [power_state.RUNNING, 512, 512, None, None]
        race = fakelibvirt.make_libvirtError(
            fakelibvirt.libvirtError,
            'ERR',
            error_code=fakelibvirt.VIR_ERR_OPERATION_FAILED,
            error_message='cannot read cputime for domain')

        mock_has_min_version.return_value = True

        domain.info.return_value = expected
        actual = compat.get_domain_info(fakelibvirt, test_host, domain)
        self.assertEqual(actual, expected)
        self.assertEqual(domain.info.call_count, 1)
        domain.info.reset_mock()

        domain.info.side_effect = race
        self.assertRaises(fakelibvirt.libvirtError,
                          compat.get_domain_info,
                          fakelibvirt, test_host, domain)
        self.assertEqual(domain.info.call_count, 1)
        domain.info.reset_mock()

        mock_has_min_version.return_value = False

        domain.info.side_effect = [race, expected]
        actual = compat.get_domain_info(fakelibvirt, test_host, domain)
        self.assertEqual(actual, expected)
        self.assertEqual(domain.info.call_count, 2)
        domain.info.reset_mock()

        domain.info.side_effect = race
        self.assertRaises(fakelibvirt.libvirtError,
                          compat.get_domain_info,
                          fakelibvirt, test_host, domain)
        self.assertEqual(domain.info.call_count, 2)
