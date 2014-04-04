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

from sqlalchemy import and_
from sqlalchemy import delete
from sqlalchemy import func
from sqlalchemy import MetaData
from sqlalchemy import select
from sqlalchemy import Table

from nova.openstack.common import timeutils

DELETE_CHUNK = 1000


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    quota_usages = Table('quota_usages', meta, autoload=True)
    reservations = Table('reservations', meta, autoload=True)

    resource_tuples = select(columns=[quota_usages.c.resource],
            distinct=True).execute().fetchall()
    resources = [resource[0] for resource in resource_tuples]

    for resource in ['instances', 'cores', 'ram', 'security_groups']:
        delete_null_rows(resource, quota_usages, reservations)

    for resource in ['fixed_ips', 'floating_ips', 'networks']:
        delete_per_user_rows(resource, quota_usages, reservations)

    if 'instances' in resources:
        sync_instances(meta, quota_usages)

    if 'security_groups' in resources:
        sync_security_groups(meta, quota_usages)

    if 'floating_ips' in resources:
        sync_floating_ips(meta, quota_usages)

    if 'fixed_ips' in resources:
        sync_fixed_ips(meta, quota_usages)

    if 'networks' in resources:
        sync_networks(meta, quota_usages)


def delete_null_rows(resource, quota_usages, reservations):
    res_query = select(columns=[reservations.c.uuid],
            from_obj=[reservations.join(quota_usages,
                reservations.c.usage_id == quota_usages.c.id)],
            whereclause=quota_usages.c.user_id == None)

    res_uuids = []
    for (uuid,) in res_query.execute():
        res_uuids.append(uuid)

    if len(res_uuids) > 0:
        for i in xrange(0, len(res_uuids), DELETE_CHUNK):
            uuids = res_uuids[i:i + DELETE_CHUNK]
            delete(reservations,
                    whereclause=reservations.c.uuid.in_(uuids)).execute()

    delete(quota_usages, whereclause=and_(quota_usages.c.user_id == None,
        quota_usages.c.resource == resource)).execute()


def delete_per_user_rows(resource, quota_usages, reservations):
    res_query = select(columns=[reservations.c.uuid],
            from_obj=[reservations.join(quota_usages,
                reservations.c.usage_id == quota_usages.c.id)],
            whereclause=quota_usages.c.user_id != None)

    res_uuids = []
    for (uuid,) in res_query.execute():
        res_uuids.append(uuid)

    if len(res_uuids) > 0:
        for i in xrange(0, len(res_uuids), DELETE_CHUNK):
            uuids = res_uuids[i:i + DELETE_CHUNK]
            delete(reservations,
                    whereclause=reservations.c.uuid.in_(uuids)).execute()

    delete(quota_usages, whereclause=and_(quota_usages.c.user_id != None,
        quota_usages.c.resource == resource)).execute()


def sync_instances(meta, quota_usages):
    instances = Table('instances', meta, autoload=True)

    usage = select(
                columns=[instances.c.user_id, instances.c.project_id,
                    func.count(instances.c.id), func.sum(instances.c.vcpus),
                    func.sum(instances.c.memory_mb)],
                whereclause=instances.c.deleted == 0,
                group_by=[instances.c.user_id, instances.c.project_id])

    resources = ['instances', 'cores', 'ram']
    for (user_id, project_id, instances, cores,
            ram) in usage.execute():

        res_dict = {'instances': instances, 'cores': cores, 'ram': ram}
        for resource in resources:
            _insert_or_update_quota_usages(quota_usages, user_id, project_id,
                    resource, res_dict[resource])


def sync_security_groups(meta, quota_usages):
    security_groups = Table('security_groups', meta, autoload=True)

    usage = select(
            columns=[security_groups.c.user_id, security_groups.c.project_id,
                func.count(security_groups.c.id)],
            whereclause=security_groups.c.deleted == 0,
            group_by=[security_groups.c.user_id, security_groups.c.project_id])

    for (user_id, project_id, sec_groups_count) in usage.execute():
        _insert_or_update_quota_usages(quota_usages, user_id, project_id,
                'security_groups', sec_groups_count)


def sync_floating_ips(meta, quota_usages):
    floating_ips = Table('floating_ips', meta, autoload=True)

    usage = select(
            columns=[floating_ips.c.project_id,
                func.count(floating_ips.c.id)],
            whereclause=and_(floating_ips.c.deleted == 0,
                floating_ips.c.auto_assigned == False),
            group_by=floating_ips.c.project_id)

    for (project_id, floating_ips_count) in usage.execute():
        _insert_or_update_quota_usages(quota_usages, None, project_id,
                'floating_ips', floating_ips_count)


def sync_fixed_ips(meta, quota_usages):
    fixed_ips = Table('fixed_ips', meta, autoload=True)
    instances = Table('instances', meta, autoload=True)

    usage = select(
            columns=[instances.c.project_id,
                func.count(fixed_ips.c.id)],
            from_obj=[fixed_ips.join(instances,
                instances.c.uuid == fixed_ips.c.instance_uuid)],
            whereclause=fixed_ips.c.deleted == 0,
            group_by=instances.c.project_id)

    for (project_id, fixed_ips_count) in usage.execute():
        _insert_or_update_quota_usages(quota_usages, None, project_id,
                'fixed_ips', fixed_ips_count)


def sync_networks(meta, quota_usages):
    networks = Table('networks', meta, autoload=True)

    usage = select(
            columns=[networks.c.project_id,
                func.count(networks.c.id)],
            whereclause=networks.c.deleted == 0,
            group_by=networks.c.project_id)

    for (project_id, networks_count) in usage.execute():
        _insert_or_update_quota_usages(quota_usages, None, project_id,
                'networks', networks_count)


def _insert_or_update_quota_usages(quota_usages, user_id, project_id, resource,
        in_use):

    now = timeutils.utcnow()
    quota = select(columns=[quota_usages.c.user_id],
            whereclause=and_(quota_usages.c.user_id == user_id,
                quota_usages.c.project_id == project_id,
                quota_usages.c.resource == resource)).execute().fetchone()

    if not quota:
        quota_usages.insert().values(created_at=now, updated_at=now,
                project_id=project_id, resource=resource, in_use=in_use,
                reserved=0, deleted=0, user_id=user_id).execute()
    else:
        quota_usages.update().where(and_(quota_usages.c.user_id == user_id,
            quota_usages.c.project_id == project_id,
            quota_usages.c.resource == resource)).values(updated_at=now,
                    in_use=in_use).execute()


def downgrade(migrate_engine):
    # The state of the quota_usages table before this migration is either that
    # it's up to date with usage numbers or it's out of sync due to the per
    # user quota addition.  After the migration it's either still in sync or
    # has just become in sync with actual usage numbers.  Given that,
    # downgrading to either the same state or an out of sync state doesn't make
    # sense.  It may be worth noting that the sync logic used here is copied
    # from what happens when quotas are configured to be refreshed in the db
    # api.  See quota_reserve() in db/sqlalchemy/api.py.
    pass
