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

import datetime

from sqlalchemy import *
from migrate import *

from nova import log as logging
from nova import utils

meta = MetaData()


def upgrade(migrate_engine):
    meta.bind = migrate_engine
    dialect = migrate_engine.url.get_dialect().name

    # grab tables
    fixed_ips = Table('fixed_ips', meta, autoload=True)
    virtual_interfaces = Table('virtual_interfaces', meta, autoload=True)

    # add foreignkey if not sqlite
    try:
        if not dialect.startswith('sqlite'):
            ForeignKeyConstraint(columns=[fixed_ips.c.virtual_interface_id],
                                 refcolumns=[virtual_interfaces.c.id]).create()
    except Exception:
        logging.error(_("foreign key constraint couldn't be added"))
        raise


def downgrade(migrate_engine):
    meta.bind = migrate_engine
    dialect = migrate_engine.url.get_dialect().name

    # drop foreignkey if not sqlite
    try:
        if not dialect.startswith('sqlite'):
            ForeignKeyConstraint(columns=[fixed_ips.c.virtual_interface_id],
                                 refcolumns=[virtual_interfaces.c.id]).drop()
    except Exception:
        logging.error(_("foreign key constraint couldn't be dropped"))
        raise
