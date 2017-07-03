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


from oslo_db.sqlalchemy import utils
from sqlalchemy import Column
from sqlalchemy import MetaData
from sqlalchemy import String

from nova.db.sqlalchemy import api


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    shadow_prefix = api._SHADOW_TABLE_PREFIX
    uuid_col = Column('uuid', String(36))

    pci_devices = utils.get_table(migrate_engine, 'pci_devices')
    if not hasattr(pci_devices.c, 'uuid'):
        pci_devices.create_column(uuid_col.copy())

    shadow_pci_devices = utils.get_table(migrate_engine,
                                         shadow_prefix + 'pci_devices')
    if not hasattr(shadow_pci_devices.c, 'uuid'):
        shadow_pci_devices.create_column(uuid_col.copy())
