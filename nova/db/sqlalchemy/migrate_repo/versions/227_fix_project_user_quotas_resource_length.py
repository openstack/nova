# Copyright 2013 NEC Corporation
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

from sqlalchemy import MetaData, String, Table


def upgrade(migrate_engine):
    meta = MetaData(bind=migrate_engine)
    table = Table('project_user_quotas', meta, autoload=True)
    col_resource = getattr(table.c, 'resource')

    if col_resource.type.length == 25:
        # The resource of project_user_quotas table had been changed to
        # invalid length(25) since I56ad98d3702f53fe8cfa94093fea89074f7a5e90.
        # The following code fixes the length for the environments which are
        # deployed after I56ad98d3702f53fe8cfa94093fea89074f7a5e90.
        col_resource.alter(type=String(255))
        table.update().where(table.c.resource == 'injected_file_content_byt')\
            .values(resource='injected_file_content_bytes').execute()
