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

from sqlalchemy import MetaData, Table, func, select
from sqlalchemy.sql import and_

from nova import exception
from nova.i18n import _


def upgrade(migrate_engine):
    meta = MetaData(migrate_engine)
    instances = Table('instances', meta, autoload=True)
    sysmeta = Table('instance_system_metadata', meta, autoload=True)
    count = select([func.count()]).select_from(sysmeta).where(
        and_(instances.c.uuid == sysmeta.c.instance_uuid,
             sysmeta.c.key == 'instance_type_id',
             sysmeta.c.deleted != sysmeta.c.id,
             instances.c.deleted != instances.c.id)).execute().scalar()
    if count > 0:
        msg = _('There are still %(count)i unmigrated flavor records. '
                'Migration cannot continue until all instance flavor '
                'records have been migrated to the new format. Please run '
                '`nova-manage db migrate_flavor_data\' first.') % {
                    'count': count}
        raise exception.ValidationError(detail=msg)
