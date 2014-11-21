#    Copyright 2011 OpenStack Foundation
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


class ContextTestCase(test.NoDBTestCase):

    def test_request_context_elevated(self):
        user_ctxt = context.RequestContext('111',
                                           '222',
                                           admin=False)
        self.assertFalse(user_ctxt.is_admin)
        admin_ctxt = user_ctxt.elevated()
        self.assertTrue(admin_ctxt.is_admin)
        self.assertIn('admin', admin_ctxt.roles)
        self.assertFalse(user_ctxt.is_admin)
        self.assertNotIn('admin', user_ctxt.roles)

    def test_request_context_sets_is_admin(self):
        ctxt = context.RequestContext('111',
                                      '222',
                                      roles=['admin', 'weasel'])
        self.assertEqual(ctxt.is_admin, True)

    def test_request_context_sets_is_admin_by_role(self):
        ctxt = context.RequestContext('111',
                                      '222',
                                      roles=['administrator'])
        self.assertEqual(ctxt.is_admin, True)

    def test_request_context_sets_is_admin_upcase(self):
        ctxt = context.RequestContext('111',
                                      '222',
                                      roles=['Admin', 'weasel'])
        self.assertEqual(ctxt.is_admin, True)

    def test_request_context_read_deleted(self):
        ctxt = context.RequestContext('111',
                                      '222',
                                      read_deleted='yes')
        self.assertEqual(ctxt.read_deleted, 'yes')

        ctxt.read_deleted = 'no'
        self.assertEqual(ctxt.read_deleted, 'no')

    def test_request_context_read_deleted_invalid(self):
        self.assertRaises(ValueError,
                          context.RequestContext,
                          '111',
                          '222',
                          read_deleted=True)

        ctxt = context.RequestContext('111', '222')
        self.assertRaises(ValueError,
                          setattr,
                          ctxt,
                          'read_deleted',
                          True)

    def test_extra_args_to_context_get_logged(self):
        info = {}

        def fake_warn(log_msg):
            info['log_msg'] = log_msg

        self.stubs.Set(context.LOG, 'warning', fake_warn)

        c = context.RequestContext('user', 'project',
                extra_arg1='meow', extra_arg2='wuff')
        self.assertTrue(c)
        self.assertIn("'extra_arg1': 'meow'", info['log_msg'])
        self.assertIn("'extra_arg2': 'wuff'", info['log_msg'])

    def test_service_catalog_default(self):
        ctxt = context.RequestContext('111', '222')
        self.assertEqual(ctxt.service_catalog, [])

        ctxt = context.RequestContext('111', '222',
                service_catalog=[])
        self.assertEqual(ctxt.service_catalog, [])

        ctxt = context.RequestContext('111', '222',
                service_catalog=None)
        self.assertEqual(ctxt.service_catalog, [])

    def test_service_catalog_cinder_only(self):
        service_catalog = [
                {u'type': u'compute', u'name': u'nova'},
                {u'type': u's3', u'name': u's3'},
                {u'type': u'image', u'name': u'glance'},
                {u'type': u'volume', u'name': u'cinder'},
                {u'type': u'ec2', u'name': u'ec2'},
                {u'type': u'object-store', u'name': u'swift'},
                {u'type': u'identity', u'name': u'keystone'},
                {u'type': None, u'name': u'S_withouttype'},
                {u'type': u'vo', u'name': u'S_partofvolume'}]

        volume_catalog = [{u'type': u'volume', u'name': u'cinder'}]
        ctxt = context.RequestContext('111', '222',
                service_catalog=service_catalog)
        self.assertEqual(ctxt.service_catalog, volume_catalog)

    def test_to_dict_from_dict_no_log(self):
        warns = []

        def stub_warn(msg, *a, **kw):
            if (a and len(a) == 1 and isinstance(a[0], dict) and a[0]):
                a = a[0]
            warns.append(str(msg) % a)

        self.stubs.Set(context.LOG, 'warn', stub_warn)

        ctxt = context.RequestContext('111',
                                      '222',
                                      roles=['admin', 'weasel'])

        ctxt = context.RequestContext.from_dict(ctxt.to_dict())

        self.assertEqual(len(warns), 0, warns)
