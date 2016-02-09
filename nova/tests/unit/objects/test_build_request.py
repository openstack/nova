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

from nova import exception
from nova import objects
from nova.objects import build_request
from nova.tests.unit import fake_build_request
from nova.tests.unit.objects import test_objects


class _TestBuildRequestObject(object):

    @mock.patch.object(build_request.BuildRequest,
            '_get_by_instance_uuid_from_db')
    def test_get_by_instance_uuid(self, get_by_uuid):
        fake_req = fake_build_request.fake_db_req()
        get_by_uuid.return_value = fake_req

        req_obj = build_request.BuildRequest.get_by_instance_uuid(self.context,
                fake_req['request_spec']['instance_uuid'])

        self.assertEqual(fake_req['request_spec']['instance_uuid'],
                         req_obj.request_spec.instance_uuid)
        self.assertEqual(fake_req['project_id'], req_obj.project_id)
        self.assertIsInstance(req_obj.request_spec, objects.RequestSpec)
        get_by_uuid.assert_called_once_with(self.context,
                fake_req['request_spec']['instance_uuid'])

    @mock.patch.object(build_request.BuildRequest,
            '_create_in_db')
    def test_create(self, create_in_db):
        fake_req = fake_build_request.fake_db_req()
        req_obj = fake_build_request.fake_req_obj(self.context, fake_req)

        def _test_create_args(self2, context, changes):
            for field in [fields for fields in
                    build_request.BuildRequest.fields if fields not in
                    ['created_at', 'updated_at', 'request_spec', 'id']]:
                self.assertEqual(fake_req[field], changes[field])
            self.assertEqual(fake_req['request_spec']['id'],
                    changes['request_spec_id'])
            return fake_req

        with mock.patch.object(build_request.BuildRequest, '_create_in_db',
                _test_create_args):
            req_obj.create()

    def test_create_id_set(self):
        req_obj = build_request.BuildRequest(self.context)
        req_obj.id = 3

        self.assertRaises(exception.ObjectActionError, req_obj.create)

    @mock.patch.object(build_request.BuildRequest, '_destroy_in_db')
    def test_destroy(self, destroy_in_db):
        req_obj = build_request.BuildRequest(self.context)
        req_obj.id = 1
        req_obj.destroy()

        destroy_in_db.assert_called_once_with(self.context, req_obj.id)


class TestBuildRequestObject(test_objects._LocalTest,
                             _TestBuildRequestObject):
    pass


class TestRemoteBuildRequestObject(test_objects._RemoteTest,
                                   _TestBuildRequestObject):
    pass
