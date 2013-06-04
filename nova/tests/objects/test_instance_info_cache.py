#    Copyright 2013 IBM Corp.
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
from nova import db
from nova.objects import instance_info_cache
from nova.tests.objects import test_objects


class _TestInstanceInfoCacheObject(object):
    def test_get_by_instance_uuid(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'instance_info_cache_get')
        db.instance_info_cache_get(ctxt, 'fake-uuid').AndReturn(
            {'instance_uuid': 'fake-uuid', 'network_info': 'foo'})
        self.mox.ReplayAll()
        obj = instance_info_cache.InstanceInfoCache.get_by_instance_uuid(
            ctxt, 'fake-uuid')
        self.assertEqual(obj.instance_uuid, 'fake-uuid')
        self.assertEqual(obj.network_info, 'foo')
        self.assertRemotes()

    def test_save(self):
        ctxt = context.get_admin_context()
        self.mox.StubOutWithMock(db, 'instance_info_cache_update')
        db.instance_info_cache_update(ctxt, 'fake-uuid',
                                      {'network_info': 'foo'})
        self.mox.ReplayAll()
        obj = instance_info_cache.InstanceInfoCache()
        obj._context = ctxt
        obj.instance_uuid = 'fake-uuid'
        obj.network_info = 'foo'
        obj.save()


class TestInstanceInfoCacheObject(test_objects._LocalTest,
                                  _TestInstanceInfoCacheObject):
    pass


class TestInstanceInfoCacheObjectRemote(test_objects._RemoteTest,
                                        _TestInstanceInfoCacheObject):
    pass
