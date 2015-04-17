# Copyright 2014 Red Hat, Inc.
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
    """Remove the instance_group_metadata table."""
    meta = MetaData(bind=migrate_engine)

    if migrate_engine.has_table('instance_group_metadata'):
        group_metadata = Table('instance_group_metadata', meta, autoload=True)
        group_metadata.drop()

    if migrate_engine.has_table('shadow_instance_group_metadata'):
        shadow_group_metadata = Table('shadow_instance_group_metadata', meta,
                                      autoload=True)
        shadow_group_metadata.drop()
