# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright 2011 OpenStack LLC
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

from nova import context
from nova import test


class ContextTestCase(test.TestCase):

    def test_request_context_sets_is_admin(self):
        ctxt = context.RequestContext('111',
                                      '222',
                                      roles=['admin', 'weasel'])
        self.assertEquals(ctxt.is_admin, True)

    def test_request_context_sets_is_admin_upcase(self):
        ctxt = context.RequestContext('111',
                                      '222',
                                      roles=['Admin', 'weasel'])
        self.assertEquals(ctxt.is_admin, True)

    def test_request_context_read_deleted(self):
        ctxt = context.RequestContext('111',
                                      '222',
                                      read_deleted='yes')
        self.assertEquals(ctxt.read_deleted, 'yes')

    def test_request_context_read_deleted_invalid(self):
        self.assertRaises(ValueError,
                          context.RequestContext,
                          '111',
                          '222',
                          read_deleted=True)

    def test_extra_args_to_context_get_logged(self):
        info = {}

        def fake_warn(log_msg):
            info['log_msg'] = log_msg

        self.stubs.Set(context.LOG, 'warn', fake_warn)

        c = context.RequestContext('user', 'project',
                extra_arg1='meow', extra_arg2='wuff')
        self.assertTrue(c)
        self.assertIn("'extra_arg1': 'meow'", info['log_msg'])
        self.assertIn("'extra_arg2': 'wuff'", info['log_msg'])
