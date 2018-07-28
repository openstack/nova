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
from oslo_utils.fixture import uuidsentinel as uuids

from nova.compute import api as compute_api
from nova import context as nova_context
from nova import exception
from nova import objects
from nova import test
from nova.tests import fixtures as nova_fixtures


class ComputeAPITestCase(test.NoDBTestCase):
    USES_DB_SELF = True

    def setUp(self):
        super(ComputeAPITestCase, self).setUp()
        self.useFixture(nova_fixtures.Database(database='api'))

    @mock.patch('nova.objects.instance_mapping.InstanceMapping.create')
    def test_reqspec_buildreq_instmapping_single_transaction(self,
                                                             mock_create):
        # Simulate a DBError during an INSERT by raising an exception from the
        # InstanceMapping.create method.
        mock_create.side_effect = test.TestingException('oops')

        ctxt = nova_context.RequestContext('fake-user', 'fake-project')
        rs = objects.RequestSpec(context=ctxt, instance_uuid=uuids.inst)
        # project_id and instance cannot be None
        br = objects.BuildRequest(context=ctxt, instance_uuid=uuids.inst,
                                  project_id=ctxt.project_id,
                                  instance=objects.Instance())
        im = objects.InstanceMapping(context=ctxt, instance_uuid=uuids.inst)

        self.assertRaises(
            test.TestingException,
            compute_api.API._create_reqspec_buildreq_instmapping, ctxt, rs, br,
            im)

        # Since the instance mapping failed to INSERT, we should not have
        # written a request spec record or a build request record.
        self.assertRaises(
            exception.RequestSpecNotFound,
            objects.RequestSpec.get_by_instance_uuid, ctxt, uuids.inst)
        self.assertRaises(
            exception.BuildRequestNotFound,
            objects.BuildRequest.get_by_instance_uuid, ctxt, uuids.inst)
