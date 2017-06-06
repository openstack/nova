# Copyright 2011 Eldar Nugaev
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

import mock
from oslo_serialization import jsonutils
from webob import exc

from nova.api.openstack.compute import server_diagnostics
from nova.api.openstack import wsgi as os_wsgi
from nova.compute import api as compute_api
from nova import exception
from nova import objects
from nova import test
from nova.tests.unit.api.openstack import fakes

import oslo_messaging

UUID = 'abc'


def fake_instance_get(self, _context, instance_uuid, expected_attrs=None):
    if instance_uuid != UUID:
        raise Exception("Invalid UUID")
    return objects.Instance(uuid=instance_uuid, host='123')


class ServerDiagnosticsTestV21(test.NoDBTestCase):
    mock_diagnostics_method = 'get_diagnostics'
    api_version = '2.1'

    def _setup_router(self):
        self.router = fakes.wsgi_app_v21()

    def _get_request(self):
        return fakes.HTTPRequest.blank(
            '/v2/fake/servers/%s/diagnostics' % UUID,
            version=self.api_version,
            headers = {os_wsgi.API_VERSION_REQUEST_HEADER:
                           'compute %s' % self.api_version})

    def setUp(self):
        super(ServerDiagnosticsTestV21, self).setUp()
        self._setup_router()

    @mock.patch.object(compute_api.API, 'get', fake_instance_get)
    def _test_get_diagnostics(self, expected, return_value):
        req = self._get_request()
        with mock.patch.object(compute_api.API, self.mock_diagnostics_method,
                               return_value=return_value):
            res = req.get_response(self.router)
        output = jsonutils.loads(res.body)
        self.assertEqual(expected, output)

    def test_get_diagnostics(self):
        diagnostics = {'data': 'Some diagnostics info'}
        self._test_get_diagnostics(diagnostics, diagnostics)

    @mock.patch.object(compute_api.API, 'get',
                side_effect=exception.InstanceNotFound(instance_id=UUID))
    def test_get_diagnostics_with_non_existed_instance(self, mock_get):
        req = self._get_request()
        res = req.get_response(self.router)
        self.assertEqual(res.status_int, 404)

    @mock.patch.object(compute_api.API, 'get', fake_instance_get)
    def test_get_diagnostics_raise_conflict_on_invalid_state(self):
        req = self._get_request()
        with mock.patch.object(compute_api.API, self.mock_diagnostics_method,
                side_effect=exception.InstanceInvalidState('fake message')):
            res = req.get_response(self.router)
        self.assertEqual(409, res.status_int)

    @mock.patch.object(compute_api.API, 'get', fake_instance_get)
    def test_get_diagnostics_raise_instance_not_ready(self):
        req = self._get_request()
        with mock.patch.object(compute_api.API, self.mock_diagnostics_method,
                side_effect=exception.InstanceNotReady('fake message')):
            res = req.get_response(self.router)
        self.assertEqual(409, res.status_int)

    @mock.patch.object(compute_api.API, 'get', fake_instance_get)
    def test_get_diagnostics_raise_no_notimplementederror(self):
        req = self._get_request()
        with mock.patch.object(compute_api.API, self.mock_diagnostics_method,
                               side_effect=NotImplementedError):
            res = req.get_response(self.router)
        self.assertEqual(501, res.status_int)


class ServerDiagnosticsTestV248(ServerDiagnosticsTestV21):
    mock_diagnostics_method = 'get_instance_diagnostics'
    api_version = '2.48'

    def test_get_diagnostics(self):
        return_value = objects.Diagnostics(
            config_drive=False,
            state='running',
            driver='libvirt',
            uptime=5,
            hypervisor='hypervisor',
            # hypervisor_os is unset
            cpu_details=[
                objects.CpuDiagnostics(id=0, time=1111, utilisation=11),
                objects.CpuDiagnostics(id=1, time=None, utilisation=22),
                objects.CpuDiagnostics(id=2, time=3333, utilisation=None),
                objects.CpuDiagnostics(id=None, time=4444, utilisation=44)],
            nic_details=[objects.NicDiagnostics(
                mac_address='de:ad:be:ef:00:01',
                rx_drop=1,
                rx_errors=2,
                rx_octets=3,
                rx_packets=4,
                rx_rate=5,
                tx_drop=6,
                tx_errors=7,
                tx_octets=8,
                # tx_packets is unset
                tx_rate=None)],
            disk_details=[objects.DiskDiagnostics(
                errors_count=1,
                read_bytes=2,
                read_requests=3,
                # write_bytes is unset
                write_requests=None)],
            num_cpus=4,
            num_disks=1,
            num_nics=1,
            memory_details=objects.MemoryDiagnostics(maximum=8192, used=3072))

        expected = {
            'config_drive': False,
            'state': 'running',
            'driver': 'libvirt',
            'uptime': 5,
            'hypervisor': 'hypervisor',
            'hypervisor_os': None,
            'cpu_details': [{'id': 0, 'time': 1111, 'utilisation': 11},
                            {'id': 1, 'time': None, 'utilisation': 22},
                            {'id': 2, 'time': 3333, 'utilisation': None},
                            {'id': None, 'time': 4444, 'utilisation': 44}],
            'nic_details': [{'mac_address': 'de:ad:be:ef:00:01',
                             'rx_drop': 1,
                             'rx_errors': 2,
                             'rx_octets': 3,
                             'rx_packets': 4,
                             'rx_rate': 5,
                             'tx_drop': 6,
                             'tx_errors': 7,
                             'tx_octets': 8,
                             'tx_packets': None,
                             'tx_rate': None}],
            'disk_details': [{'errors_count': 1,
                              'read_bytes': 2,
                              'read_requests': 3,
                              'write_bytes': None,
                              'write_requests': None}],
            'num_cpus': 4,
            'num_disks': 1,
            'num_nics': 1,
            'memory_details': {'maximum': 8192, 'used': 3072}}

        self._test_get_diagnostics(expected, return_value)

    @mock.patch.object(oslo_messaging.RPCClient, 'can_send_version',
                       return_value=False)
    @mock.patch.object(compute_api.API, 'get', fake_instance_get)
    def test_get_diagnostics_old_compute(self, mock_version):
        """Checks case when env has new api and old compute."""

        controller = server_diagnostics.ServerDiagnosticsController()
        req = self._get_request()
        self.assertRaises(exc.HTTPBadRequest, controller.index, req, UUID)


class ServerDiagnosticsEnforcementV21(test.NoDBTestCase):
    api_version = '2.1'

    def setUp(self):
        super(ServerDiagnosticsEnforcementV21, self).setUp()
        self.controller = server_diagnostics.ServerDiagnosticsController()
        self.req = fakes.HTTPRequest.blank('', version=self.api_version)

    def test_get_diagnostics_policy_failed(self):
        rule_name = "os_compute_api:os-server-diagnostics"
        self.policy.set_rules({rule_name: "project:non_fake"})
        exc = self.assertRaises(
            exception.PolicyNotAuthorized,
            self.controller.index, self.req, fakes.FAKE_UUID)
        self.assertEqual(
            "Policy doesn't allow %s to be performed." % rule_name,
            exc.format_message())


class ServerDiagnosticsEnforcementV248(ServerDiagnosticsEnforcementV21):
    api_version = '2.48'
