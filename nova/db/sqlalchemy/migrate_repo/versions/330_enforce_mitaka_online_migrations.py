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

from sqlalchemy import MetaData, Table, and_, func, select

from nova import exception
from nova.i18n import _


WARNING_MSG = _('There are still %(count)i unmigrated records in '
                'the %(table)s table. Migration cannot continue '
                'until all records have been migrated.')


def upgrade(migrate_engine):
    meta = MetaData(migrate_engine)
    compute_nodes = Table('compute_nodes', meta, autoload=True)
    aggregates = Table('aggregates', meta, autoload=True)

    for table in (compute_nodes, aggregates):
        count = select([func.count()]).select_from(table).where(and_(
            table.c.deleted == 0,
            table.c.uuid == None)).execute().scalar()  # NOQA
        if count > 0:
            msg = WARNING_MSG % {
                'count': count,
                'table': table.name,
            }
            raise exception.ValidationError(detail=msg)

    pci_devices = Table('pci_devices', meta, autoload=True)

    # Ensure that all non-deleted PCI device records have a populated
    # parent address. Note that we test directly against the 'type-VF'
    # enum value to prevent issues with this migration going forward
    # if the definition is altered.
    count = select([func.count()]).select_from(pci_devices).where(and_(
        pci_devices.c.deleted == 0,
        pci_devices.c.parent_addr == None,
        pci_devices.c.dev_type == 'type-VF')).execute().scalar()  # NOQA
    if count > 0:
        msg = WARNING_MSG % {
            'count': count,
            'table': pci_devices.name,
        }
        raise exception.ValidationError(detail=msg)
