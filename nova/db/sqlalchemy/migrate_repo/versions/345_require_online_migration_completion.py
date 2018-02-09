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

# This is a placeholder for backports.
# Do not use this number for new work.  New work starts after
# all the placeholders.
#
# See this for more information:
# http://lists.openstack.org/pipermail/openstack-dev/2013-March/006827.html

from sqlalchemy import MetaData, Table, func, select

from nova import exception
from nova.i18n import _


def upgrade(migrate_engine):
    meta = MetaData(migrate_engine)
    instance_types = Table('instance_types', meta, autoload=True)
    keypairs = Table('key_pairs', meta, autoload=True)
    aggregates = Table('aggregates', meta, autoload=True)
    instance_groups = Table('instance_groups', meta, autoload=True)

    base_msg = _('Migration cannot continue until all these have '
                 'been migrated to the api database. Please run '
                 '`nova-manage db online_data_migrations\' on Newton '
                 'code before continuing.')

    count = select([func.count()]).select_from(instance_types).where(
        instance_types.c.deleted == 0).scalar()
    if count:
        msg = (base_msg +
               _(' There are still %(count)i unmigrated flavors. ') % {
                   'count': count})
        raise exception.ValidationError(detail=msg)

    count = select([func.count()]).select_from(keypairs).where(
        keypairs.c.deleted == 0).scalar()
    if count:
        msg = (base_msg +
               _(' There are still %(count)i unmigrated keypairs. ') % {
                   'count': count})
        raise exception.ValidationError(detail=msg)

    count = select([func.count()]).select_from(aggregates).where(
        aggregates.c.deleted == 0).scalar()
    if count:
        msg = (base_msg +
               _(' There are still %(count)i unmigrated aggregates. ') % {
                   'count': count})
        raise exception.ValidationError(detail=msg)

    count = select([func.count()]).select_from(instance_groups).where(
        instance_groups.c.deleted == 0).scalar()
    if count:
        msg = (base_msg +
               _(' There are still %(count)i unmigrated instance groups. ') % {
                   'count': count})
        raise exception.ValidationError(detail=msg)
