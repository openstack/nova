# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 Red Hat, Inc.
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

LOG = logging.getLogger(__name__)


def run(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    # NOTE(dprince): The old dns_domains table is in the 'latin1'
    # charset and had its primary key length set to 512.
    # This is too long to be a valid pkey in the 'utf8' table charset
    # and is the root cause of errors like:
    #
    # 1) Dumping a database with mysqldump and trying to import it fails
    #    because this table is latin1 but fkeys to utf8 tables (projects).
    #
    # 2) Trying to alter the old dns_domains table fails with errors like:
    #    mysql> ALTER TABLE dns_domains DROP PRIMARY KEY;
    #    ERROR 1025 (HY000): Error on rename of './nova/#sql-6cf_855'....
    #
    # In short this table is just in a bad state. So... lets create a new one
    # with a shorter 'domain' column which is valid for the utf8 charset.
    #
    # Since this is stable/essex we fix the table without bumping
    # the migration number. The same upgrade will run during Folsom but
    # that won't hurt anything.
    #
    # https://bugs.launchpad.net/nova/+bug/993663
    dns_domains_old = Table('dns_domains', meta, autoload=True)
    domain_type = str(dns_domains_old.c.domain.type)
    if migrate_engine.name == 'mysql' and domain_type == 'VARCHAR(512)':
        LOG.audit('Applying database fix for Essex dns_domains table.')
        dns_domains_old.rename(name='dns_domains_old')

        #Bind new metadata to avoid issues after the rename
        meta = MetaData()
        meta.bind = migrate_engine
        projects = Table('projects', meta, autoload=True)  # Required for fkey

        dns_domains_new = Table('dns_domains', meta,
            Column('created_at', DateTime),
            Column('updated_at', DateTime),
            Column('deleted_at', DateTime),
            Column('deleted', Boolean),
            Column('domain', String(length=255), nullable=False,
                   primary_key=True),
            Column('scope', String(length=255)),
            Column('availability_zone', String(length=255)),
            Column('project_id', String(length=255),
                   ForeignKey('projects.id')),
            mysql_engine='InnoDB',
            mysql_charset='utf8',
        )
        dns_domains_new.create()

        dns_domains_old = Table('dns_domains_old', meta, autoload=True)
        record_list = list(dns_domains_old.select().execute())
        for rec in record_list:
            row = dns_domains_new.insert()
            row.execute({'created_at': rec['created_at'],
                        'updated_at': rec['updated_at'],
                        'deleted_at': rec['deleted_at'],
                        'deleted': rec['deleted'],
                        'domain': rec['domain'],
                        'scope': rec['scope'],
                        'availability_zone': rec['availability_zone'],
                        'project_id': rec['project_id'],
                        })

        dns_domains_old.drop()
