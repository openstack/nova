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

from oslo_log import log as logging
from sqlalchemy import MetaData, Table, func, select

from nova import exception
from nova.i18n import _
from nova import objects

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    flavors = Table('flavors', meta, autoload=True)
    count = select([func.count()]).select_from(flavors).scalar()
    if count == 0:
        # NOTE(danms): We need to be careful here if this is a new
        # installation, which can't possibly have any mappings. Check
        # to see if any flavors are defined to determine if we are
        # upgrading an existing system. If not, then don't obsess over
        # the lack of mappings
        return

    cell_mappings = Table('cell_mappings', meta, autoload=True)
    count = select([func.count()]).select_from(cell_mappings).scalar()
    # Two mappings are required at a minimum, cell0 and your first cell
    if count < 2:
        msg = _('Cell mappings are not created, but required for Ocata. '
                'Please run nova-manage cell_v2 simple_cell_setup before '
                'continuing.')
        raise exception.ValidationError(detail=msg)

    count = select([func.count()]).select_from(cell_mappings).where(
        cell_mappings.c.uuid == objects.CellMapping.CELL0_UUID).scalar()
    if count != 1:
        msg = _('A mapping for Cell0 was not found, but is required for '
                'Ocata. Please run nova-manage cell_v2 simple_cell_setup '
                'before continuing.')
        raise exception.ValidationError(detail=msg)

    host_mappings = Table('host_mappings', meta, autoload=True)
    count = select([func.count()]).select_from(host_mappings).scalar()
    if count == 0:
        LOG.warning('No host mappings were found, but are required for Ocata. '
                    'Please run nova-manage cell_v2 simple_cell_setup before '
                    'continuing.')
