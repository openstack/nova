# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

import webob
import webob.dec
import webob.exc

from nova.api import ec2
from nova import context
from nova import exception
from nova import flags
from nova import test
from nova import utils

from xml.etree.ElementTree import fromstring as xml_to_tree

FLAGS = flags.FLAGS


@webob.dec.wsgify
def conditional_forbid(req):
    """Helper wsgi app returns 403 if param 'die' is 1."""
    if 'die' in req.params and req.params['die'] == '1':
        raise webob.exc.HTTPForbidden()
    return 'OK'


class LockoutTestCase(test.TestCase):
    """Test case for the Lockout middleware."""
    def setUp(self):  # pylint: disable=C0103
        super(LockoutTestCase, self).setUp()
        utils.set_time_override()
        self.lockout = ec2.Lockout(conditional_forbid)

    def tearDown(self):  # pylint: disable=C0103
        utils.clear_time_override()
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
        self._send_bad_attempts('test', FLAGS.lockout_attempts)
        self.assertTrue(self._is_locked_out('test'))

    def test_timeout(self):
        self._send_bad_attempts('test', FLAGS.lockout_attempts)
        self.assertTrue(self._is_locked_out('test'))
        utils.advance_time_seconds(FLAGS.lockout_minutes * 60)
        self.assertFalse(self._is_locked_out('test'))

    def test_multiple_keys(self):
        self._send_bad_attempts('test1', FLAGS.lockout_attempts)
        self.assertTrue(self._is_locked_out('test1'))
        self.assertFalse(self._is_locked_out('test2'))
        utils.advance_time_seconds(FLAGS.lockout_minutes * 60)
        self.assertFalse(self._is_locked_out('test1'))
        self.assertFalse(self._is_locked_out('test2'))

    def test_window_timeout(self):
        self._send_bad_attempts('test', FLAGS.lockout_attempts - 1)
        self.assertFalse(self._is_locked_out('test'))
        utils.advance_time_seconds(FLAGS.lockout_window * 60)
        self._send_bad_attempts('test', FLAGS.lockout_attempts - 1)
        self.assertFalse(self._is_locked_out('test'))


class ExecutorTestCase(test.TestCase):
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
        tree = xml_to_tree(result.body)
        return tree.findall('./Errors')[0].find('Error/Message').text

    def test_instance_not_found(self):
        def not_found(context):
            raise exception.InstanceNotFound(instance_id=5)
        result = self._execute(not_found)
        self.assertIn('i-00000005', self._extract_message(result))

    def test_snapshot_not_found(self):
        def not_found(context):
            raise exception.SnapshotNotFound(snapshot_id=5)
        result = self._execute(not_found)
        self.assertIn('snap-00000005', self._extract_message(result))

    def test_volume_not_found(self):
        def not_found(context):
            raise exception.VolumeNotFound(volume_id=5)
        result = self._execute(not_found)
        self.assertIn('vol-00000005', self._extract_message(result))
