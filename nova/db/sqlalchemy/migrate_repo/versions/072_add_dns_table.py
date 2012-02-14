# Copyright 2012 Andrew Bogott for The Wikimedia Foundation
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
from sqlalchemy import MetaData, String, Table
from nova import log as logging

meta = MetaData()
LOG = logging.getLogger(__name__)

#
# New Tables
#
dns_domains = Table('dns_domains', meta,
        Column('created_at', DateTime(timezone=False)),
        Column('updated_at', DateTime(timezone=False)),
        Column('deleted_at', DateTime(timezone=False)),
        Column('deleted', Boolean(create_constraint=True, name=None)),
        Column('domain',
               String(length=512, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False),
               primary_key=True, nullable=False),
        Column('scope',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)),
        Column('availability_zone',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False)),
        Column('project_id',
               String(length=255, convert_unicode=False, assert_unicode=None,
                      unicode_error=None, _warn_on_bytestring=False),
               ForeignKey('projects.id'))
        )


def upgrade(migrate_engine):
    meta.bind = migrate_engine

    # load instances for fk
    instances = Table('projects', meta, autoload=True)

    # create dns_domains table
    try:
        dns_domains.create()
    except Exception:
        LOG.error(_("Table |%s| not created!"), repr(dns_domains))
        raise


def downgrade(migrate_engine):
    try:
        dns_domains.drop()
    except Exception:
        LOG.error(_("dns_domains table not dropped"))
        raise
