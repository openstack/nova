# Copyright (c) 2013 OpenStack Foundation
# All Rights Reserved.
#
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

import abc
import functools
import os

import fixtures
import six

from nova.openstack.common.db.sqlalchemy import session
from nova.openstack.common.db.sqlalchemy import utils
from nova.openstack.common import test


class DbFixture(fixtures.Fixture):
    """Basic database fixture.

    Allows to run tests on various db backends, such as SQLite, MySQL and
    PostgreSQL. By default use sqlite backend. To override default backend
    uri set env variable OS_TEST_DBAPI_CONNECTION with database admin
    credentials for specific backend.
    """

    def _get_uri(self):
        return os.getenv('OS_TEST_DBAPI_CONNECTION', 'sqlite://')

    def __init__(self, test):
        super(DbFixture, self).__init__()

        self.test = test

    def setUp(self):
        super(DbFixture, self).setUp()

        self.test.engine = session.create_engine(self._get_uri())
        self.test.sessionmaker = session.get_maker(self.test.engine)
        self.addCleanup(self.test.engine.dispose)


class DbTestCase(test.BaseTestCase):
    """Base class for testing of DB code.

    Using `DbFixture`. Intended to be the main database test case to use all
    the tests on a given backend with user defined uri. Backend specific
    tests should be decorated with `backend_specific` decorator.
    """

    FIXTURE = DbFixture

    def setUp(self):
        super(DbTestCase, self).setUp()
        self.useFixture(self.FIXTURE(self))


ALLOWED_DIALECTS = ['sqlite', 'mysql', 'postgresql']


def backend_specific(*dialects):
    """Decorator to skip backend specific tests on inappropriate engines.

    ::dialects: list of dialects names under which the test will be launched.
    """
    def wrap(f):
        @functools.wraps(f)
        def ins_wrap(self):
            if not set(dialects).issubset(ALLOWED_DIALECTS):
                raise ValueError(
                    "Please use allowed dialects: %s" % ALLOWED_DIALECTS)
            if self.engine.name not in dialects:
                msg = ('The test "%s" can be run '
                       'only on %s. Current engine is %s.')
                args = (f.__name__, ' '.join(dialects), self.engine.name)
                self.skip(msg % args)
            else:
                return f(self)
        return ins_wrap
    return wrap


@six.add_metaclass(abc.ABCMeta)
class OpportunisticFixture(DbFixture):
    """Base fixture to use default CI databases.

    The databases exist in OpenStack CI infrastructure. But for the
    correct functioning in local environment the databases must be
    created manually.
    """

    DRIVER = abc.abstractproperty(lambda: None)
    DBNAME = PASSWORD = USERNAME = 'openstack_citest'

    def _get_uri(self):
        return utils.get_connect_string(backend=self.DRIVER,
                                        user=self.USERNAME,
                                        passwd=self.PASSWORD,
                                        database=self.DBNAME)


@six.add_metaclass(abc.ABCMeta)
class OpportunisticTestCase(DbTestCase):
    """Base test case to use default CI databases.

    The subclasses of the test case are running only when openstack_citest
    database is available otherwise a tests will be skipped.
    """

    FIXTURE = abc.abstractproperty(lambda: None)

    def setUp(self):
        credentials = {
            'backend': self.FIXTURE.DRIVER,
            'user': self.FIXTURE.USERNAME,
            'passwd': self.FIXTURE.PASSWORD,
            'database': self.FIXTURE.DBNAME}

        if self.FIXTURE.DRIVER and not utils.is_backend_avail(**credentials):
            msg = '%s backend is not available.' % self.FIXTURE.DRIVER
            return self.skip(msg)

        super(OpportunisticTestCase, self).setUp()


class MySQLOpportunisticFixture(OpportunisticFixture):
    DRIVER = 'mysql'


class PostgreSQLOpportunisticFixture(OpportunisticFixture):
    DRIVER = 'postgresql'


class MySQLOpportunisticTestCase(OpportunisticTestCase):
    FIXTURE = MySQLOpportunisticFixture


class PostgreSQLOpportunisticTestCase(OpportunisticTestCase):
    FIXTURE = PostgreSQLOpportunisticFixture
