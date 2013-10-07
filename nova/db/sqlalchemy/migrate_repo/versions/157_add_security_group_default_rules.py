# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table
from nova.db.sqlalchemy import types

from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    security_group_default_rules = Table('security_group_default_rules', meta,
        Column('created_at', DateTime),
        Column('updated_at', DateTime),
        Column('deleted_at', DateTime),
        Column('deleted', Integer, default=0),
        Column('id', Integer, primary_key=True, nullable=False),
        Column('protocol', String(length=5)),
        Column('from_port', Integer),
        Column('to_port', Integer),
        Column('cidr', types.CIDR()),
        mysql_engine='InnoDB',
        mysql_charset='utf8',
    )

    try:
        security_group_default_rules.create()
    except Exception:
        msg = "Exception while creating table 'security_group_default_rules"
        LOG.exception(msg)
        raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    security_group_default_rules = Table('security_group_default_rules',
                                         meta,
                                         autoload=True)
    try:
        security_group_default_rules.drop()
    except Exception:
        msg = "Exception while dropping table 'security_group_default_rules'"
        LOG.exception(msg)
        raise
