# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import nova.context
from nova.db import api as db
from nova import objects
from nova import test


class InstanceListWithOldDeletedServiceTestCase(test.TestCase):

    def setUp(self):
        super(InstanceListWithOldDeletedServiceTestCase, self).setUp()
        self.context = nova.context.RequestContext('fake-user', 'fake-project')

    def test_instance_list_old_deleted_service_with_no_uuid(self):
        # Create a nova-compute service record with a host that will match the
        # instance's host, with no uuid. We can't do this through the
        # Service object because it will automatically generate a uuid.
        # Use service version 9, which is too old compared to the minimum
        # version in the rest of the deployment.
        service = db.service_create(self.context, {'host': 'fake-host',
                                                   'binary': 'nova-compute',
                                                   'version': 9})
        self.assertIsNone(service['uuid'])

        # Now delete it.
        db.service_destroy(self.context, service['id'])

        # Create a new service with the same host name that has a UUID and a
        # current version.
        new_service = objects.Service(context=self.context, host='fake-host',
                                      binary='nova-compute')
        new_service.create()

        # Create an instance whose host will match both services, including the
        # deleted one.
        inst = objects.Instance(context=self.context,
                                project_id=self.context.project_id,
                                host='fake-host')
        inst.create()

        insts = objects.InstanceList.get_by_filters(
            self.context, {}, expected_attrs=['services'])
        self.assertEqual(1, len(insts))
        self.assertEqual(2, len(insts[0].services))
        # Deleted service should not have a UUID
        for service in insts[0].services:
            if service.deleted:
                self.assertNotIn('uuid', service)
            else:
                self.assertIsNotNone(service.uuid)
