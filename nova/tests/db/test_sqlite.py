# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# Copyright 2010 OpenStack Foundation
# All Rights Reserved.
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

"""Test cases for sqlite-specific logic"""

from nova.openstack.common import processutils
from nova import test
from nova import utils
import os
from sqlalchemy import create_engine
from sqlalchemy import Column, BigInteger, String
from sqlalchemy.ext.declarative import declarative_base


class TestSqlite(test.NoDBTestCase):
    """Tests for sqlite-specific logic."""

    def setUp(self):
        super(TestSqlite, self).setUp()
        self.db_file = "test_bigint.sqlite"
        if os.path.exists(self.db_file):
            os.remove(self.db_file)

    def test_big_int_mapping(self):
        base_class = declarative_base()

        class User(base_class):
            """Dummy class with a BigInteger column for testing."""
            __tablename__ = "users"
            id = Column(BigInteger, primary_key=True)
            name = Column(String)

        get_schema_cmd = "sqlite3 %s '.schema'" % self.db_file
        engine = create_engine("sqlite:///%s" % self.db_file)
        base_class.metadata.create_all(engine)
        try:
            output, _ = utils.execute(get_schema_cmd, shell=True)
        except processutils.ProcessExecutionError as e:
            # NOTE(alaski): If this check becomes necessary in other tests it
            # should be moved into setUp.
            if 'not found' in str(e):
                self.skipTest(str(e))
            else:
                raise
        self.assertFalse('BIGINT' in output, msg="column type BIGINT "
                         "not converted to INTEGER in schema")

    def tearDown(self):
        if os.path.exists(self.db_file):
            os.remove(self.db_file)
        super(TestSqlite, self).tearDown()
