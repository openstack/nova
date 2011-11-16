# Copyright 2011 OpenStack LLC.
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

from sqlalchemy import Column, Integer, Float, MetaData, Table

meta = MetaData()


def _get_table(table_name):
    return Table(table_name, meta, autoload=True)

rxtx_base = Column('rxtx_base', Integer)
rxtx_factor = Column('rxtx_factor', Float, default=1)
rxtx_quota = Column('rxtx_quota', Integer)
rxtx_cap = Column('rxtx_cap', Integer)


def upgrade(migrate_engine):
    meta.bind = migrate_engine
    instance_types = _get_table('instance_types')
    networks = _get_table('networks')

    instance_types.create_column(rxtx_factor)
    networks.create_column(rxtx_base)

    base = migrate_engine.execute(_("select min(rxtx_cap) as min_rxtx from "\
                                    "instance_types where rxtx_cap > 0"))\
                                    .scalar()
    base = base if base > 1 else 1
    update_i_type_sql = _("update instance_types set rxtx_factor = rxtx_cap"\
                            "/%s where rxtx_cap > 0" % base)
    migrate_engine.execute(update_i_type_sql)
    migrate_engine.execute("update networks set rxtx_base = %s" % base)

    instance_types.c.rxtx_quota.drop()
    instance_types.c.rxtx_cap.drop()


def downgrade(migrate_engine):
    meta.bind = migrate_engine
    instance_types = _get_table('instance_types')
    networks = _get_table('networks')

    instance_types.create_column(rxtx_quota)
    instance_types.create_column(rxtx_cap)

    base = migrate_engine.execute(_("select min(rxtx_base) from networks "\
                                    "where rxtx_base > 0")).scalar()
    base = base if base > 1 else 1

    update_i_type_sql = (_("update instance_types set rxtx_cap = " \
                         "rxtx_factor * %s" % base))
    migrate_engine.execute(update_i_type_sql)

    instance_types.c.rxtx_factor.drop()
    networks.c.rxtx_base.drop()
