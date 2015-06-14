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

from sqlalchemy import create_engine
from sqlalchemy import Column, BigInteger, String
import sqlalchemy.engine.reflection
from sqlalchemy.ext.declarative import declarative_base

from nova import test


class TestSqlite(test.NoDBTestCase):
    """Tests for sqlite-specific logic."""

    def test_big_int_mapping(self):
        base_class = declarative_base()

        class User(base_class):
            """Dummy class with a BigInteger column for testing."""
            __tablename__ = "users"
            id = Column(BigInteger, primary_key=True)
            name = Column(String)

        engine = create_engine('sqlite://')
        base_class.metadata.create_all(engine)

        insp = sqlalchemy.engine.reflection.Inspector.from_engine(engine)

        id_type = None
        for column in insp.get_columns('users'):
            if column['name'] == 'id':
                id_type = column['type'].compile()

        # NOTE(russellb) We have a hook in nova.db.sqlalchemy that makes it so
        # BigInteger() is compiled to INTEGER for sqlite instead of BIGINT.

        self.assertEqual('INTEGER', id_type)
