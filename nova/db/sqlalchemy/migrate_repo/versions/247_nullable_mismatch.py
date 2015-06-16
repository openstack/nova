# Copyright 2014 OpenStack Foundation
# All Rights Reserved
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


from sqlalchemy import MetaData, Table


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)

    quota_usages = Table('quota_usages', meta, autoload=True)
    quota_usages.c.resource.alter(nullable=False)

    pci_devices = Table('pci_devices', meta, autoload=True)
    # NOTE(mriedem): The deleted column is in a UniqueConstraint so making
    # it nullable breaks DB2 with an SQL0542N error, so skip for DB2. There is
    # a FKey in 246 so we're kind of stuck with DB2 since we can't create the
    # FKey without the unique constraint and we can't have a unique constraint
    # on a nullable column.
    # TODO(mriedem): Revisit this once the deleted column (inherited from the
    # SoftDeleteMixin in oslo.db) is non-null on all tables, which is going
    # to be a non-trivial effort.
    if migrate_engine.name != 'ibm_db_sa':
        pci_devices.c.deleted.alter(nullable=True)
    pci_devices.c.product_id.alter(nullable=False)
    pci_devices.c.vendor_id.alter(nullable=False)
    pci_devices.c.dev_type.alter(nullable=False)
