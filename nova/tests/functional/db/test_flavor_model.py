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

from nova.db.sqlalchemy import api_models
from nova.db.sqlalchemy import models
from nova import test


class FlavorTablesCompareTestCase(test.NoDBTestCase):
    def _get_columns_list(self, model):
        columns_list = [m.key for m in model.__table__.columns]
        return columns_list

    def _check_column_list(self, columns_new, columns_old):
        columns_old.remove('deleted_at')
        columns_old.remove('deleted')
        intersect = set(columns_new).intersection(set(columns_old))
        if intersect != set(columns_new) or intersect != set(columns_old):
            return False
        return True

    def test_tables_flavors_instance_types(self):
        flavors = api_models.Flavors()
        instance_types = models.InstanceTypes()
        columns_flavors = self._get_columns_list(flavors)
        # The description column is only in the API database so we have to
        # exclude it from this check.
        columns_flavors.remove('description')
        columns_instance_types = self._get_columns_list(instance_types)
        self.assertTrue(self._check_column_list(columns_flavors,
                                                columns_instance_types))

    def test_tables_flavor_instance_type_extra_specs(self):
        flavor_extra_specs = api_models.FlavorExtraSpecs()
        instance_type_extra_specs = models.InstanceTypeExtraSpecs()
        columns_flavor_extra_specs = self._get_columns_list(flavor_extra_specs)
        columns_instance_type_extra_specs = self._get_columns_list(
                                                    instance_type_extra_specs)
        columns_flavor_extra_specs.remove('flavor_id')
        columns_instance_type_extra_specs.remove('instance_type_id')
        self.assertTrue(self._check_column_list(
                                            columns_flavor_extra_specs,
                                            columns_instance_type_extra_specs))

    def test_tables_flavor_instance_type_projects(self):
        flavor_projects = api_models.FlavorProjects()
        instance_types_projects = models.InstanceTypeProjects()
        columns_flavor_projects = self._get_columns_list(flavor_projects)
        columns_instance_type_projects = self._get_columns_list(
                                                    instance_types_projects)
        columns_flavor_projects.remove('flavor_id')
        columns_instance_type_projects.remove('instance_type_id')
        self.assertTrue(self._check_column_list(
                                            columns_flavor_projects,
                                            columns_instance_type_projects))
