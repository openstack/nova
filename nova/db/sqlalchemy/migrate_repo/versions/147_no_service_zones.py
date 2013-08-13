# Copyright 2012 OpenStack Foundation
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

from sqlalchemy import String, Column, MetaData, Table, select


""" Remove availability_zone column from services model and replace with
    aggregate based zone."""


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    services = Table('services', meta, autoload=True)
    aggregates = Table('aggregates', meta, autoload=True)
    aggregate_metadata = Table('aggregate_metadata', meta, autoload=True)
    # migrate data
    record_list = list(services.select().execute())
    for rec in record_list:
        # Only need to migrate nova-compute availability_zones
        if rec['binary'] != 'nova-compute':
            continue
        # if zone doesn't exist create
        result = aggregate_metadata.select().where(
            aggregate_metadata.c.key == 'availability_zone').where(
            aggregate_metadata.c.value == rec['availability_zone']).execute()
        result = [r for r in result]
        if len(result) > 0:
            agg_id = result[0].aggregate_id
        else:
            agg = aggregates.insert()
            result = agg.execute({'name': rec['availability_zone']})
            agg_id = result.inserted_primary_key[0]
            row = aggregate_metadata.insert()
            row.execute({'created_at': rec['created_at'],
                        'updated_at': rec['updated_at'],
                        'deleted_at': rec['deleted_at'],
                        'deleted': rec['deleted'],
                        'key': 'availability_zone',
                        'value': rec['availability_zone'],
                        'aggregate_id': agg_id,
                        })
        # add host to zone
        agg_hosts = Table('aggregate_hosts', meta, autoload=True)
        num_hosts = agg_hosts.count().where(
            agg_hosts.c.host == rec['host']).where(
            agg_hosts.c.aggregate_id == agg_id).execute().scalar()
        if num_hosts == 0:
            agg_hosts.insert().execute({'host': rec['host'],
                                        'aggregate_id': agg_id})

    services.drop_column('availability_zone')


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    services = Table('services', meta, autoload=True)
    aggregate_metadata = Table('aggregate_metadata', meta, autoload=True)
    agg_hosts = Table('aggregate_hosts', meta, autoload=True)
    availability_zone = Column('availability_zone', String(255),
            default='nova')
    services.create_column(availability_zone)

    # Migrate data back
    # NOTE(jhesketh): This needs to be done with individual inserts as multiple
    # results in an update sub-query do not work with MySQL. See bug/1207309.
    record_list = list(services.select().execute())
    for rec in record_list:
        # Only need to update nova-compute availability_zones
        if rec['binary'] != 'nova-compute':
            continue
        result = select([aggregate_metadata.c.value],
            from_obj=aggregate_metadata.join(
                agg_hosts,
                agg_hosts.c.aggregate_id == aggregate_metadata.c.aggregate_id
            )
        ).where(
            aggregate_metadata.c.key == 'availability_zone'
        ).where(
            agg_hosts.c.aggregate_id == aggregate_metadata.c.aggregate_id
        ).where(
            agg_hosts.c.host == rec['host']
        )

        services.update().values(
            availability_zone=list(result.execute())[0][0]
        ).where(
            services.c.id == rec['id']
        )
