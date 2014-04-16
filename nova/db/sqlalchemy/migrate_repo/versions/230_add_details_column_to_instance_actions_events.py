# Copyright 2013 OpenStack Foundation.
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

from sqlalchemy import Column, String, Text

from nova.db.sqlalchemy import api
from nova.openstack.common.db.sqlalchemy import utils


def upgrade(migrate_engine):
    actions_events = utils.get_table(migrate_engine, 'instance_actions_events')
    host = Column('host', String(255))
    details = Column('details', Text)
    actions_events.create_column(host)
    actions_events.create_column(details)
    shadow_actions_events = utils.get_table(migrate_engine,
            api._SHADOW_TABLE_PREFIX + 'instance_actions_events')
    shadow_actions_events.create_column(host.copy())
    shadow_actions_events.create_column(details.copy())


def downgrade(migrate_engine):
    actions_events = utils.get_table(migrate_engine, 'instance_actions_events')
    actions_events.drop_column('host')
    actions_events.drop_column('details')
    shadow_actions_events = utils.get_table(migrate_engine,
            api._SHADOW_TABLE_PREFIX + 'instance_actions_events')
    shadow_actions_events.drop_column('host')
    shadow_actions_events.drop_column('details')
