# Copyright (c) Intel Corporation.
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


from migrate import UniqueConstraint
from sqlalchemy import MetaData, Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine
    compute_nodes = Table('compute_nodes', meta, autoload=True)

    # Drop the old UniqueConstraint
    ukey = UniqueConstraint('host', 'hypervisor_hostname', table=compute_nodes,
                            name="uniq_compute_nodes0host0hypervisor_hostname")
    ukey.drop()

    # Add new UniqueConstraint
    ukey = UniqueConstraint(
        'host', 'hypervisor_hostname', 'deleted',
        table=compute_nodes,
        name="uniq_compute_nodes0host0hypervisor_hostname0deleted")
    ukey.create()
