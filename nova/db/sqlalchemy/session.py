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

import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import create_session

from nova import flags

FLAGS = flags.FLAGS


def managed_session(autocommit=True):
    """Helper method to grab session manager"""
    return SessionExecutionManager(autocommit=autocommit)


class SessionExecutionManager:
    """Session manager supporting with .. as syntax"""
    _engine = None
    _session = None

    def __init__(self, autocommit):
        if not self._engine:
            self._engine = create_engine(FLAGS.sql_connection, echo=False)
        self._session = create_session(bind=self._engine,
                                       autocommit=autocommit)

    def __enter__(self):
        return self._session

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type:
            logging.exception("Rolling back due to failed transaction")
            self._session.rollback()
        self._session.close()
