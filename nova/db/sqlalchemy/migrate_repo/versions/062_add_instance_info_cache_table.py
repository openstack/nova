# Copyright 2011 OpenStack LLC.
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

from sqlalchemy import Boolean, Column, DateTime, ForeignKey
from sqlalchemy import Integer, MetaData, String
from sqlalchemy import Table, Text

from nova import log as logging
from nova import utils

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # load tables for fk
    instances = Table('instances', meta, autoload=True)

    #
    # New Tables
    #
    instance_info_caches = Table('instance_info_caches', meta,
            Column('created_at', DateTime(timezone=False),
                   default=utils.utcnow()),
            Column('updated_at', DateTime(timezone=False),
                   onupdate=utils.utcnow()),
            Column('deleted_at', DateTime(timezone=False)),
            Column('deleted', Boolean(create_constraint=True, name=None)),
            Column('id', Integer(), primary_key=True),
            Column('network_info', Text()),
            Column('instance_id', String(36),
                   ForeignKey('instances.uuid'),
                   nullable=False,
                   unique=True),
            mysql_engine='InnoDB')
    # create instance_info_caches table
    try:
        instance_info_caches.create()
    except Exception:
        LOG.error(_("Table |%s| not created!"), repr(instance_info_caches))
        raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # load tables for fk
    instances = Table('instances', meta, autoload=True)

    instance_info_caches = Table('instance_info_caches', meta, autoload=True)
    try:
        instance_info_caches.drop()
    except Exception:
        LOG.error(_("instance_info_caches tables not dropped"))
        raise
