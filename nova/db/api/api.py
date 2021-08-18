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

from oslo_db.sqlalchemy import enginefacade
from oslo_utils import importutils
import sqlalchemy as sa

import nova.conf

profiler_sqlalchemy = importutils.try_import('osprofiler.sqlalchemy')

CONF = nova.conf.CONF

context_manager = enginefacade.transaction_context()

# NOTE(stephenfin): We don't need equivalents of the 'get_context_manager' or
# 'create_context_manager' APIs found in 'nova.db.main.api' since we don't need
# to be cell-aware here


def _get_db_conf(conf_group, connection=None):
    kw = dict(conf_group.items())
    if connection is not None:
        kw['connection'] = connection
    return kw


def configure(conf):
    context_manager.configure(**_get_db_conf(conf.api_database))

    if (
        profiler_sqlalchemy and
        CONF.profiler.enabled and
        CONF.profiler.trace_sqlalchemy
    ):
        context_manager.append_on_engine_create(
            lambda eng: profiler_sqlalchemy.add_tracing(sa, eng, "db"))


def get_engine():
    return context_manager.writer.get_engine()
