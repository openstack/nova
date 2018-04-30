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

from nova.api.openstack.placement import exception
from nova.api.openstack.placement.objects import project as project_obj
from nova.tests.functional.api.openstack.placement.db import test_base as tb
from nova.tests import uuidsentinel as uuids


class ProjectTestCase(tb.PlacementDbBaseTestCase):
    def test_non_existing_project(self):
        self.assertRaises(
            exception.ProjectNotFound, project_obj.Project.get_by_external_id,
            self.ctx, uuids.non_existing_project)

    def test_create_and_get(self):
        p = project_obj.Project(self.ctx, external_id='another-project')
        p.create()
        p = project_obj.Project.get_by_external_id(self.ctx, 'another-project')
        # Project ID == 1 is fake-project created in setup
        self.assertEqual(2, p.id)
        self.assertRaises(exception.ProjectExists, p.create)
