# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 Red Hat, Inc.
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

"""Tests for network API"""

from nova import context
from nova import db
from nova import network
from nova.openstack.common import rpc
from nova import test


class ApiTestCase(test.TestCase):
    def setUp(self):
        super(ApiTestCase, self).setUp()
        self.network_api = network.API()
        self.context = context.RequestContext('fake-user',
                                              'fake-project')

    def _do_test_associate_floating_ip(self, orig_instance_uuid):
        """Test post-association logic"""

        new_instance = {'uuid': 'new-uuid'}

        def fake_rpc_call(context, topic, msg):
            return orig_instance_uuid

        self.stubs.Set(rpc, 'call', fake_rpc_call)

        def fake_instance_get_by_uuid(context, instance_uuid):
            return {'uuid': instance_uuid}

        self.stubs.Set(self.network_api.db, 'instance_get_by_uuid',
                       fake_instance_get_by_uuid)

        def fake_get_nw_info(ctxt, instance):
            class FakeNWInfo(object):
                def json(self):
                    pass
            return FakeNWInfo()

        self.stubs.Set(self.network_api, '_get_instance_nw_info',
                       fake_get_nw_info)

        if orig_instance_uuid:
            expected_updated_instances = [new_instance['uuid'],
                                          orig_instance_uuid]
        else:
            expected_updated_instances = [new_instance['uuid']]

        def fake_instance_info_cache_update(context, instance_uuid, cache):
            self.assertEquals(instance_uuid,
                              expected_updated_instances.pop())

        self.stubs.Set(self.network_api.db, 'instance_info_cache_update',
                       fake_instance_info_cache_update)

        self.network_api.associate_floating_ip(self.context,
                                               new_instance,
                                               '172.24.4.225',
                                               '10.0.0.2')

    def test_associate_preassociated_floating_ip(self):
        self._do_test_associate_floating_ip('orig-uuid')

    def test_associate_unassociated_floating_ip(self):
        self._do_test_associate_floating_ip(None)
