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

from oslo_log import log as logging
from sqlalchemy import Index, MetaData, Table

from nova.i18n import _LI

LOG = logging.getLogger(__name__)


def _get_deleted_expire_index(table):
    members = sorted(['deleted', 'expire'])
    for idx in table.indexes:
        if sorted(idx.columns.keys()) == members:
            return idx


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    reservations = Table('reservations', meta, autoload=True)
    if _get_deleted_expire_index(reservations):
        LOG.info(_LI('Skipped adding reservations_deleted_expire_idx '
                     'because an equivalent index already exists.'))
        return

    # Based on expire_reservations query
    # from: nova/db/sqlalchemy/api.py
    index = Index('reservations_deleted_expire_idx',
                  reservations.c.deleted, reservations.c.expire)

    index.create(migrate_engine)
