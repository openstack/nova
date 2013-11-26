# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012, Red Hat, Inc.
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

"""
Unit Tests for nova.cert.rpcapi
"""

from oslo.config import cfg

from nova.cert import rpcapi as cert_rpcapi
from nova import context
from nova.openstack.common import rpc
from nova import test

CONF = cfg.CONF


class CertRpcAPITestCase(test.NoDBTestCase):
    def _test_cert_api(self, method, **kwargs):
        ctxt = context.RequestContext('fake_user', 'fake_project')
        rpcapi = cert_rpcapi.CertAPI()
        expected_retval = 'foo'
        expected_version = kwargs.pop('version', rpcapi.BASE_RPC_API_VERSION)
        expected_msg = rpcapi.make_msg(method, **kwargs)
        expected_msg['version'] = expected_version

        self.call_ctxt = None
        self.call_topic = None
        self.call_msg = None
        self.call_timeout = None

        def _fake_call(_ctxt, _topic, _msg, _timeout):
            self.call_ctxt = _ctxt
            self.call_topic = _topic
            self.call_msg = _msg
            self.call_timeout = _timeout
            return expected_retval

        self.stubs.Set(rpc, 'call', _fake_call)

        retval = getattr(rpcapi, method)(ctxt, **kwargs)

        self.assertEqual(retval, expected_retval)
        self.assertEqual(self.call_ctxt, ctxt)
        self.assertEqual(self.call_topic, CONF.cert_topic)
        self.assertEqual(self.call_msg, expected_msg)
        self.assertIsNone(self.call_timeout)

    def test_revoke_certs_by_user(self):
        self._test_cert_api('revoke_certs_by_user', user_id='fake_user_id')

        # NOTE(russellb) Havana compat
        self.flags(cert='havana', group='upgrade_levels')
        self._test_cert_api('revoke_certs_by_user', user_id='fake_user_id',
                version='1.0')

    def test_revoke_certs_by_project(self):
        self._test_cert_api('revoke_certs_by_project',
                            project_id='fake_project_id')

        # NOTE(russellb) Havana compat
        self.flags(cert='havana', group='upgrade_levels')
        self._test_cert_api('revoke_certs_by_project',
                            project_id='fake_project_id', version='1.0')

    def test_revoke_certs_by_user_and_project(self):
        self._test_cert_api('revoke_certs_by_user_and_project',
                            user_id='fake_user_id',
                            project_id='fake_project_id')

        # NOTE(russellb) Havana compat
        self.flags(cert='havana', group='upgrade_levels')
        self._test_cert_api('revoke_certs_by_user_and_project',
                            user_id='fake_user_id',
                            project_id='fake_project_id', version='1.0')

    def test_generate_x509_cert(self):
        self._test_cert_api('generate_x509_cert',
                            user_id='fake_user_id',
                            project_id='fake_project_id')

        # NOTE(russellb) Havana compat
        self.flags(cert='havana', group='upgrade_levels')
        self._test_cert_api('generate_x509_cert',
                            user_id='fake_user_id',
                            project_id='fake_project_id', version='1.0')

    def test_fetch_ca(self):
        self._test_cert_api('fetch_ca', project_id='fake_project_id')

        # NOTE(russellb) Havana compat
        self.flags(cert='havana', group='upgrade_levels')
        self._test_cert_api('fetch_ca', project_id='fake_project_id',
                version='1.0')

    def test_fetch_crl(self):
        self._test_cert_api('fetch_crl', project_id='fake_project_id')

        # NOTE(russellb) Havana compat
        self.flags(cert='havana', group='upgrade_levels')
        self._test_cert_api('fetch_crl', project_id='fake_project_id',
                version='1.0')

    def test_decrypt_text(self):
        self._test_cert_api('decrypt_text',
                            project_id='fake_project_id', text='blah')

        # NOTE(russellb) Havana compat
        self.flags(cert='havana', group='upgrade_levels')
        self._test_cert_api('decrypt_text',
                            project_id='fake_project_id', text='blah',
                            version='1.0')
