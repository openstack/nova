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

import sqlalchemy

from nova import log as logging


meta = sqlalchemy.MetaData()
LOG = logging.getLogger(__name__)


s3_images = sqlalchemy.Table('s3_images', meta,
                sqlalchemy.Column('created_at',
                                  sqlalchemy.DateTime(timezone=False)),
                sqlalchemy.Column('updated_at',
                                  sqlalchemy.DateTime(timezone=False)),
                sqlalchemy.Column('deleted_at',
                                  sqlalchemy.DateTime(timezone=False)),
                sqlalchemy.Column('deleted',
                       sqlalchemy.Boolean(create_constraint=True, name=None)),
                sqlalchemy.Column('id', sqlalchemy.Integer(),
                                  primary_key=True,
                                  nullable=False,
                                  autoincrement=True),
                sqlalchemy.Column('uuid', sqlalchemy.String(36),
                                  nullable=False))


def upgrade(migrate_engine):
    meta.bind = migrate_engine

    try:
        s3_images.create()
    except Exception:
        LOG.exception("Exception while creating table 's3_images'")
        meta.drop_all(tables=[s3_images])
        raise


def downgrade(migrate_engine):
    meta.bind = migrate_engine

    s3_images.drop()
