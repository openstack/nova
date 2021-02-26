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

from sqlalchemy import MetaData, Text, Table


def upgrade(migrate_engine):
    meta = MetaData()
    meta.bind = migrate_engine

    table_console_auth_tokens = Table('console_auth_tokens',
                                      meta,
                                      autoload=True)
    col_internal_access_path = getattr(table_console_auth_tokens.c,
                                       'internal_access_path')

    if col_internal_access_path.type.length == 255:
        # The internal_access_path column of console_auth_tokens table has
        # length(255) which is sometimes not enough when used with vmware
        # driver: https://bugs.launchpad.net/nova/+bug/1900371
        col_internal_access_path.alter(type=Text)
