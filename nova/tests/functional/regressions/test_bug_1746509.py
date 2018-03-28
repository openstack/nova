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
from nova import db
from nova import objects
from nova import test


class InstanceListWithServicesTestCase(test.TestCase):
    """Test the scenario listing instances whose services may not have a UUID.

    We added a UUID field to the 'services' table in Pike, so after an upgrade,
    we generate a UUID and save it to the service record upon access if it's an
    older record that does not already have a UUID.

    Now, when we list instances through the API, the instances query is joined
    with the 'services' table in order to provide service-related information.
    The bug in Pike was that we were already inside of a 'reader' database
    transaction context when we tried to compile the instance list, which
    eventually led to an error:

      TypeError: Can't upgrade a READER transaction to a WRITER mid-transaction

    because we also tried to write the newly generated service UUID to the
    service record while still nested under the 'reader' context.

    This test verifies that we are able to list instances joined with services
    even if the associated service record does not yet have a UUID.
    """
    def setUp(self):
        super(InstanceListWithServicesTestCase, self).setUp()
        self.context = nova.context.RequestContext('fake-user', 'fake-project')

    def test_instance_list_service_with_no_uuid(self):
        # Create a nova-compute service record with a host that will match the
        # instance's host, with no uuid. We can't do this through the
        # Service object because it will automatically generate a uuid.
        service = db.service_create(self.context, {'host': 'fake-host',
                                                   'binary': 'nova-compute'})
        self.assertIsNone(service['uuid'])

        # Create an instance whose host will match the service with no uuid
        inst = objects.Instance(context=self.context,
                                project_id=self.context.project_id,
                                host='fake-host')
        inst.create()

        insts = objects.InstanceList.get_by_filters(
            self.context, {}, expected_attrs=['services'])
        self.assertEqual(1, len(insts))
        self.assertEqual(1, len(insts[0].services))
        self.assertIsNotNone(insts[0].services[0].uuid)
