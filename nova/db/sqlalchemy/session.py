# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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
"""
Session Handling for SQLAlchemy backend
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, scoped_session

from nova import flags

FLAGS = flags.FLAGS

_ENGINE = None
_MAKER = None

def get_session(autocommit=True, expire_on_commit=False):
    """Helper method to grab session"""
    global _ENGINE
    global _MAKER
    if not _MAKER:
        if not _ENGINE:
            _ENGINE = create_engine(FLAGS.sql_connection, echo=False)
        _MAKER = scoped_session(sessionmaker(bind=_ENGINE,
                                autocommit=autocommit,
                                expire_on_commit=expire_on_commit))
    session =  _MAKER()
    return session
