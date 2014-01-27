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

from nova.db.sqlalchemy import utils
from nova import test


class SqlAlchemyUtilsTestCase(test.NoDBTestCase):
    """Test case for sqlaclchemy utils methods."""

    def test_modify_indexes_checks_index_before_dropping_in_postgresql(self):
        data = {"table_name": (('index2', ('old_column'),
                                ('new_column')),)}
        migrate_engine = mock.Mock()
        migrate_engine.name = 'postgresql'

        with mock.patch('nova.db.sqlalchemy.utils.reflection.Inspector'
                        '.from_engine') as inspector:
            inspector.return_value.get_indexes.return_value = [
                {'name': "index1"}]
            with mock.patch('nova.db.sqlalchemy.utils.Index') as index:
                index.return_value = mock.Mock()
                utils.modify_indexes(migrate_engine, data, False)

                self.assertFalse(index.called)
                self.assertFalse(index.return_value.drop.called)

    def test_modify_indexes_checks_index_before_dropping_in_mysql(self):
        data = {"table_name": (('index2', ('old_column'),
                                ('new_column')),)}
        migrate_engine = mock.Mock()
        migrate_engine.name = 'mysql'

        with mock.patch('nova.db.sqlalchemy.utils.reflection.Inspector'
                        '.from_engine') as inspector:
            inspector.return_value.get_indexes.return_value = [
                {'name': "index1"}]
            with mock.patch('nova.db.sqlalchemy.utils.Index') as index:
                with mock.patch('nova.db.sqlalchemy.utils.Table') as Table:
                    index.return_value = mock.Mock()
                    utils.modify_indexes(migrate_engine, data, False)

                    self.assertFalse(index.return_value.drop.called)

    def test_modify_indexes(self):
        data = {"table_name": (('index2', ('old_column'),
                                ('new_column')),)}
        migrate_engine = mock.Mock()
        migrate_engine.name = 'mysql'

        with mock.patch('nova.db.sqlalchemy.utils.reflection.Inspector'
                        '.from_engine') as inspector:
            inspector.return_value.get_indexes.return_value = [
                {'name': "index2"}]
            with mock.patch('nova.db.sqlalchemy.utils.Index') as index:
                with mock.patch('nova.db.sqlalchemy.utils.Table') as Table:
                    index.return_value = mock.Mock()
                    utils.modify_indexes(migrate_engine, data, True)

                    self.assertTrue(index.return_value.drop.called)
                    self.assertTrue(index.return_value.create.called)
