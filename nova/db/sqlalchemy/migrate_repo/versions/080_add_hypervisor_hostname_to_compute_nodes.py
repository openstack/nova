#   Copyright 2012 OpenStack, LLC
#
#   Licensed under the Apache License, Version 2.0 (the "License");
#   you may not use this file except in compliance with the License.
#   You may obtain a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS,
#   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#   See the License for the specific language governing permissions and
#   limitations under the License.

from sqlalchemy import *


meta = MetaData()

compute_nodes = Table("compute_nodes", meta, Column("id", Integer(),
        primary_key=True, nullable=False))

hypervisor_hostname = Column("hypervisor_hostname", String(255))


def upgrade(migrate_engine):
    meta.bind = migrate_engine
    compute_nodes.create_column(hypervisor_hostname)


def downgrade(migrate_engine):
    meta.bind = migrate_engine
    compute_nodes.drop_column(hypervisor_hostname)
