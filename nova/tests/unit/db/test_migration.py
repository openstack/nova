# Copyright 2014 IBM Corp.
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

from unittest import mock
import urllib

from alembic.runtime import migration as alembic_migration
from sqlalchemy.engine import url as sa_url

from nova.db.api import api as api_db_api
from nova.db.main import api as main_db_api
from nova.db import migration
from nova import exception
from nova import test
from nova.tests import fixtures as nova_fixtures


class TestDBURL(test.NoDBTestCase):
    USES_DB_SELF = True

    def test_db_sync_with_special_symbols_in_connection_string(self):
        qargs = 'read_default_group=data with/a+percent_%-and%20symbols!'
        url = f"sqlite:///:memory:?{qargs}"
        self.flags(connection=url, group='database')
        self.useFixture(nova_fixtures.Database())

        alembic_config = migration._find_alembic_conf()
        with mock.patch.object(
                migration, '_find_alembic_conf', return_value=alembic_config):
            migration.db_sync()
        actual = alembic_config.get_main_option('sqlalchemy.url')
        expected = (
            "sqlite:///:memory:?read_default_group=data+with%2Fa"
            "+percent_%25-and+symbols%21"
        )
        self.assertEqual(expected, actual)
        self.assertEqual(
            urllib.parse.unquote_plus(url),
            urllib.parse.unquote_plus(actual)
        )


class TestDBSync(test.NoDBTestCase):

    def test_db_sync_invalid_database(self):
        """We only have two databases."""
        self.assertRaises(
            exception.Invalid, migration.db_sync, database='invalid')

    def test_db_sync_legacy_version(self):
        """We don't allow users to request legacy versions."""
        self.assertRaises(
            exception.Invalid,
            migration.db_sync, '402')

    @mock.patch.object(migration, '_upgrade_alembic')
    @mock.patch.object(migration, '_find_alembic_conf')
    @mock.patch.object(migration, '_get_engine')
    def test_db_sync(self, mock_get_engine, mock_find_conf, mock_upgrade):

        # return an encoded URL to mimic sqlalchemy
        mock_get_engine.return_value.url = sa_url.make_url(
            'mysql+pymysql://nova:pass@192.168.24.3/nova?'
            'read_default_file=%2Fetc%2Fmy.cnf.d%2Fnova.cnf'
            '&read_default_group=nova'
        )

        migration.db_sync()

        mock_get_engine.assert_called_once_with('main', context=None)
        mock_find_conf.assert_called_once_with('main')
        mock_find_conf.return_value.set_main_option.assert_called_once_with(
            'sqlalchemy.url',
            'mysql+pymysql://nova:pass@192.168.24.3/nova?'  # ...
            'read_default_file=%%2Fetc%%2Fmy.cnf.d%%2Fnova.cnf'  # ...
            '&read_default_group=nova'
        )

        mock_upgrade.assert_called_once_with(
            mock_get_engine.return_value, mock_find_conf.return_value, None,
        )


@mock.patch.object(alembic_migration.MigrationContext, 'configure')
@mock.patch.object(migration, '_get_engine')
class TestDBVersion(test.NoDBTestCase):

    def test_db_version_invalid_database(
        self, mock_get_engine, mock_m_context_configure,
    ):
        """We only have two databases."""
        self.assertRaises(
            exception.Invalid, migration.db_version, database='invalid')

    def test_db_version(self, mock_get_engine, mock_m_context_configure):
        """Database is controlled by alembic."""
        ret = migration.db_version('main')
        mock_m_context = mock_m_context_configure.return_value
        self.assertEqual(
            mock_m_context.get_current_revision.return_value,
            ret
        )

        mock_get_engine.assert_called_once_with('main', context=None)
        mock_m_context_configure.assert_called_once()


class TestGetEngine(test.NoDBTestCase):

    def test_get_main_engine(self):
        with mock.patch.object(
            main_db_api, 'get_engine', return_value='engine',
        ) as mock_get_engine:
            engine = migration._get_engine()
            self.assertEqual('engine', engine)
            mock_get_engine.assert_called_once_with(context=None)

    def test_get_api_engine(self):
        with mock.patch.object(
            api_db_api, 'get_engine', return_value='engine',
        ) as mock_get_engine:
            engine = migration._get_engine('api')
            self.assertEqual('engine', engine)
            mock_get_engine.assert_called_once_with()
