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


INDEX_NAME = 'block_device_mapping_instance_uuid_virtual_name_device_name_idx'


def upgrade(migrate_engine):
    """Remove duplicate index from block_device_mapping table."""

    meta = MetaData(bind=migrate_engine)

    bdm = Table('block_device_mapping', meta, autoload=True)
    for index in bdm.indexes:
        if index.name == INDEX_NAME:
            index.drop()
