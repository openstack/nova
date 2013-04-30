# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 OpenStack Foundation
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

#
# This migration adds the availability_zone to the volume_usage_cache table.
#
# This table keeps a cache of the volume usage. Every minute (or what ever
# is configured for volume_usage_poll_interval value) one row in this table
# gets updated for each attached volume. After this patch is applied, for
# any currently attached volumes, the value will immediately be null, but
# will get updated to the correct value on the next tick of the volume
# usage poll.
#
# The volume usage poll function is the only code to access this table. The
# sequence of operation in that function is to first update the field with
# the correct value and then to pass the updated data to the consumer.
#
# Hence this new column does not need to be pre-populated.
#

from sqlalchemy import MetaData, String, Table, Column

from nova.openstack.common import log as logging

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    volume_usage_cache = Table('volume_usage_cache', meta, autoload=True)
    availability_zone = Column('availability_zone', String(255))
    volume_usage_cache.create_column(availability_zone)


def downgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    volume_usage_cache = Table('volume_usage_cache', meta, autoload=True)
    volume_usage_cache.drop_column('availability_zone')
