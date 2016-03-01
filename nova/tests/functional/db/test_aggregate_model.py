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


class AggregateTablesCompareTestCase(test.NoDBTestCase):
    def _get_column_list(self, model):
        column_list = [m.key for m in model.__table__.columns]
        return column_list

    def _check_column_list(self,
                           columns_new,
                           columns_old,
                           added=None,
                           removed=None):
        for c in added or []:
            columns_new.remove(c)
        for c in removed or []:
            columns_old.remove(c)
        intersect = set(columns_new).intersection(set(columns_old))
        if intersect != set(columns_new) or intersect != set(columns_old):
            return False
        return True

    def _compare_models(self, m_a, m_b,
                        added=None, removed=None):
        added = added or []
        removed = removed or ['deleted_at', 'deleted']
        c_a = self._get_column_list(m_a)
        c_b = self._get_column_list(m_b)
        self.assertTrue(self._check_column_list(c_a, c_b,
                                                added=added,
                                                removed=removed))

    def test_tables_aggregate_hosts(self):
        self._compare_models(api_models.AggregateHost(),
                             models.AggregateHost())

    def test_tables_aggregate_metadata(self):
        self._compare_models(api_models.AggregateMetadata(),
                             models.AggregateMetadata())

    def test_tables_aggregates(self):
        self._compare_models(api_models.Aggregate(),
                             models.Aggregate())
