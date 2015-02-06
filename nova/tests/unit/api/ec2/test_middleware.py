# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

from lxml import etree
import mock
from oslo_config import cfg
from oslo_utils import timeutils
import requests
import webob
import webob.dec
import webob.exc

from nova.api import ec2
from nova import context
from nova import exception
from nova import test
from nova import wsgi

CONF = cfg.CONF


@webob.dec.wsgify
def conditional_forbid(req):
    """Helper wsgi app returns 403 if param 'die' is 1."""
    if 'die' in req.params and req.params['die'] == '1':
        raise webob.exc.HTTPForbidden()
    return 'OK'


class LockoutTestCase(test.NoDBTestCase):
    """Test case for the Lockout middleware."""
    def setUp(self):
        super(LockoutTestCase, self).setUp()
        timeutils.set_time_override()
        self.lockout = ec2.Lockout(conditional_forbid)

    def tearDown(self):
        timeutils.clear_time_override()
        super(LockoutTestCase, self).tearDown()

    def _send_bad_attempts(self, access_key, num_attempts=1):
        """Fail x."""
        for i in xrange(num_attempts):
            req = webob.Request.blank('/?AWSAccessKeyId=%s&die=1' % access_key)
            self.assertEqual(req.get_response(self.lockout).status_int, 403)

    def _is_locked_out(self, access_key):
        """Sends a test request to see if key is locked out."""
        req = webob.Request.blank('/?AWSAccessKeyId=%s' % access_key)
        return (req.get_response(self.lockout).status_int == 403)

    def test_lockout(self):
        self._send_bad_attempts('test', CONF.lockout_attempts)
        self.assertTrue(self._is_locked_out('test'))

    def test_timeout(self):
        self._send_bad_attempts('test', CONF.lockout_attempts)
        self.assertTrue(self._is_locked_out('test'))
        timeutils.advance_time_seconds(CONF.lockout_minutes * 60)
        self.assertFalse(self._is_locked_out('test'))

    def test_multiple_keys(self):
        self._send_bad_attempts('test1', CONF.lockout_attempts)
        self.assertTrue(self._is_locked_out('test1'))
        self.assertFalse(self._is_locked_out('test2'))
        timeutils.advance_time_seconds(CONF.lockout_minutes * 60)
        self.assertFalse(self._is_locked_out('test1'))
        self.assertFalse(self._is_locked_out('test2'))

    def test_window_timeout(self):
        self._send_bad_attempts('test', CONF.lockout_attempts - 1)
        self.assertFalse(self._is_locked_out('test'))
        timeutils.advance_time_seconds(CONF.lockout_window * 60)
        self._send_bad_attempts('test', CONF.lockout_attempts - 1)
        self.assertFalse(self._is_locked_out('test'))


class ExecutorTestCase(test.NoDBTestCase):
    def setUp(self):
        super(ExecutorTestCase, self).setUp()
        self.executor = ec2.Executor()

    def _execute(self, invoke):
        class Fake(object):
            pass
        fake_ec2_request = Fake()
        fake_ec2_request.invoke = invoke

        fake_wsgi_request = Fake()

        fake_wsgi_request.environ = {
                'nova.context': context.get_admin_context(),
                'ec2.request': fake_ec2_request,
        }
        return self.executor(fake_wsgi_request)

    def _extract_message(self, result):
        tree = etree.fromstring(result.body)
        return tree.findall('./Errors')[0].find('Error/Message').text

    def _extract_code(self, result):
        tree = etree.fromstring(result.body)
        return tree.findall('./Errors')[0].find('Error/Code').text

    def test_instance_not_found(self):
        def not_found(context):
            raise exception.InstanceNotFound(instance_id=5)
        result = self._execute(not_found)
        self.assertIn('i-00000005', self._extract_message(result))
        self.assertEqual('InvalidInstanceID.NotFound',
                         self._extract_code(result))

    def test_instance_not_found_none(self):
        def not_found(context):
            raise exception.InstanceNotFound(instance_id=None)

        # NOTE(mikal): we want no exception to be raised here, which was what
        # was happening in bug/1080406
        result = self._execute(not_found)
        self.assertIn('None', self._extract_message(result))
        self.assertEqual('InvalidInstanceID.NotFound',
                         self._extract_code(result))

    def test_snapshot_not_found(self):
        def not_found(context):
            raise exception.SnapshotNotFound(snapshot_id=5)
        result = self._execute(not_found)
        self.assertIn('snap-00000005', self._extract_message(result))
        self.assertEqual('InvalidSnapshot.NotFound',
                         self._extract_code(result))

    def test_volume_not_found(self):
        def not_found(context):
            raise exception.VolumeNotFound(volume_id=5)
        result = self._execute(not_found)
        self.assertIn('vol-00000005', self._extract_message(result))
        self.assertEqual('InvalidVolume.NotFound', self._extract_code(result))


class FakeResponse(object):
    reason = "Test Reason"

    def __init__(self, status_code=400):
        self.status_code = status_code

    def json(self):
        return {}


class KeystoneAuthTestCase(test.NoDBTestCase):
    def setUp(self):
        super(KeystoneAuthTestCase, self).setUp()
        self.kauth = ec2.EC2KeystoneAuth(conditional_forbid)

    def _validate_ec2_error(self, response, http_status, ec2_code):
        self.assertEqual(response.status_code, http_status,
                         'Expected HTTP status %s' % http_status)
        root_e = etree.XML(response.body)
        self.assertEqual(root_e.tag, 'Response',
                         "Top element must be Response.")
        errors_e = root_e.find('Errors')
        error_e = errors_e[0]
        code_e = error_e.find('Code')
        self.assertIsNotNone(code_e, "Code element must be present.")
        self.assertEqual(code_e.text, ec2_code)

    def test_no_signature(self):
        req = wsgi.Request.blank('/test')
        resp = self.kauth(req)
        self._validate_ec2_error(resp, 400, 'AuthFailure')

    def test_no_key_id(self):
        req = wsgi.Request.blank('/test')
        req.GET['Signature'] = 'test-signature'
        resp = self.kauth(req)
        self._validate_ec2_error(resp, 400, 'AuthFailure')

    @mock.patch.object(requests, 'request', return_value=FakeResponse())
    def test_communication_failure(self, mock_request):
        req = wsgi.Request.blank('/test')
        req.GET['Signature'] = 'test-signature'
        req.GET['AWSAccessKeyId'] = 'test-key-id'
        resp = self.kauth(req)
        self._validate_ec2_error(resp, 400, 'AuthFailure')
        mock_request.assert_called_with('POST', CONF.keystone_ec2_url,
                                        data=mock.ANY, headers=mock.ANY,
                                        verify=mock.ANY, cert=mock.ANY)

    @mock.patch.object(requests, 'request', return_value=FakeResponse(200))
    def test_no_result_data(self, mock_request):
        req = wsgi.Request.blank('/test')
        req.GET['Signature'] = 'test-signature'
        req.GET['AWSAccessKeyId'] = 'test-key-id'
        resp = self.kauth(req)
        self._validate_ec2_error(resp, 400, 'AuthFailure')
        mock_request.assert_called_with('POST', CONF.keystone_ec2_url,
                                        data=mock.ANY, headers=mock.ANY,
                                        verify=mock.ANY, cert=mock.ANY)
