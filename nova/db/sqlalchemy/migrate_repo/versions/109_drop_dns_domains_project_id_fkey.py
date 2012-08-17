# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC.
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

from migrate import ForeignKeyConstraint
from sqlalchemy import MetaData, Table

from nova.openstack.common import log as logging


LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    dns_domains = Table('dns_domains', meta, autoload=True)
    projects = Table('projects', meta, autoload=True)

    fkeys = list(dns_domains.c.project_id.foreign_keys)
    if fkeys:
        try:
            fkey_name = fkeys[0].constraint.name
            ForeignKeyConstraint(
                columns=[dns_domains.c.project_id],
                refcolumns=[projects.c.id],
                name=fkey_name).drop()
        except Exception:
            LOG.error(_("foreign key constraint couldn't be removed"))
            raise


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    dns_domains = Table('dns_domains', meta, autoload=True)
    projects = Table('projects', meta, autoload=True)

    kwargs = {
        'columns': [dns_domains.c.project_id],
        'refcolumns': [projects.c.id],
    }

    if migrate_engine.name == 'mysql':
        # For MySQL we name our fkeys explicitly so they match Essex
        kwargs['name'] = 'dns_domains_ibfk_1'

    ForeignKeyConstraint(**kwargs).create()
