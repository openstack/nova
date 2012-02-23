# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from sqlalchemy import Boolean, Column, DateTime, Integer
from sqlalchemy import MetaData, String, Table
from nova import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    #
    # New Tables
    #
    s3_images = Table('s3_images', meta,
                    Column('created_at',
                                      DateTime(timezone=False)),
                    Column('updated_at',
                                      DateTime(timezone=False)),
                    Column('deleted_at',
                                      DateTime(timezone=False)),
                    Column('deleted',
                           Boolean(create_constraint=True, name=None)),
                    Column('id', Integer(),
                                      primary_key=True,
                                      nullable=False,
                                      autoincrement=True),
                    Column('uuid', String(36),
                                      nullable=False))
    try:
        s3_images.create()
    except Exception:
        LOG.exception("Exception while creating table 's3_images'")
        meta.drop_all(tables=[s3_images])
        raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    s3_images = Table('s3_images', meta, autoload=True)
    s3_images.drop()
