#    Copyright 2012 IBM Corp.
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

import mox

from nova.compute import manager as compute_manager
from nova import context
from nova import db
from nova import test
from nova.virt import fake
from nova.virt import virtapi


class VirtAPIBaseTest(test.NoDBTestCase, test.APICoverage):

    cover_api = virtapi.VirtAPI

    def setUp(self):
        super(VirtAPIBaseTest, self).setUp()
        self.context = context.RequestContext('fake-user', 'fake-project')
        self.set_up_virtapi()

    def set_up_virtapi(self):
        self.virtapi = virtapi.VirtAPI()

    def assertExpected(self, method, *args, **kwargs):
        self.assertRaises(NotImplementedError,
                          getattr(self.virtapi, method), self.context,
                          *args, **kwargs)

    def test_instance_update(self):
        self.assertExpected('instance_update', 'fake-uuid',
                            dict(host='foohost'))

    def test_provider_fw_rule_get_all(self):
        self.assertExpected('provider_fw_rule_get_all')

    def test_agent_build_get_by_triple(self):
        self.assertExpected('agent_build_get_by_triple',
                            'fake-hv', 'gnu/hurd', 'fake-arch')

    def test_block_device_mapping_get_all_by_instance(self):
        self.assertExpected('block_device_mapping_get_all_by_instance',
                            {'uuid': 'fake_uuid'}, legacy=False)


class FakeVirtAPITest(VirtAPIBaseTest):

    cover_api = fake.FakeVirtAPI

    def set_up_virtapi(self):
        self.virtapi = fake.FakeVirtAPI()

    def assertExpected(self, method, *args, **kwargs):
        if method == 'instance_update':
            # NOTE(danms): instance_update actually becomes the other variant
            # in FakeVirtAPI
            db_method = 'instance_update_and_get_original'
        else:
            db_method = method
        self.mox.StubOutWithMock(db, db_method)

        if method in ('aggregate_metadata_add', 'aggregate_metadata_delete',
                      'security_group_rule_get_by_security_group'):
            # NOTE(danms): FakeVirtAPI will convert the first argument to
            # argument['id'], so expect that in the actual db call
            e_args = tuple([args[0]['id']] + list(args[1:]))
        elif method in ('security_group_get_by_instance',
                        'block_device_mapping_get_all_by_instance'):
            e_args = tuple([args[0]['uuid']] + list(args[1:]))
        else:
            e_args = args

        if method == 'block_device_mapping_get_all_by_instance':
            e_kwargs = {}
        else:
            e_kwargs = kwargs

        getattr(db, db_method)(self.context, *e_args, **e_kwargs).AndReturn(
                'it worked')
        self.mox.ReplayAll()
        result = getattr(self.virtapi, method)(self.context, *args, **kwargs)
        self.assertEqual(result, 'it worked')


class FakeCompute(object):
    def __init__(self):
        self.conductor_api = mox.MockAnything()
        self.db = mox.MockAnything()

    def _instance_update(self, context, instance_uuid, **kwargs):
        # NOTE(danms): Fake this behavior from compute/manager::ComputeManager
        return self.conductor_api.instance_update(context,
                                                  instance_uuid, kwargs)


class ComputeVirtAPITest(VirtAPIBaseTest):

    cover_api = compute_manager.ComputeVirtAPI

    def set_up_virtapi(self):
        self.compute = FakeCompute()
        self.virtapi = compute_manager.ComputeVirtAPI(self.compute)

    def assertExpected(self, method, *args, **kwargs):
        self.mox.StubOutWithMock(self.compute.conductor_api, method)
        getattr(self.compute.conductor_api, method)(
            self.context, *args, **kwargs).AndReturn('it worked')
        self.mox.ReplayAll()
        result = getattr(self.virtapi, method)(self.context, *args, **kwargs)
        self.assertEqual(result, 'it worked')
