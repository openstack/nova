#!/usr/bin/env python

import argparse
import glob
import os
import subprocess

BASE = 'nova/db/sqlalchemy/migrate_repo/versions'.split('/')
API_BASE = 'nova/db/sqlalchemy/api_migrations/migrate_repo/versions'.split('/')

STUB = """
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


def upgrade(migrate_engine):
    pass
"""


def get_last_migration(base):
    path = os.path.join(*tuple(base + ['[0-9]*.py']))
    migrations = sorted([os.path.split(fn)[-1] for fn in glob.glob(path)])
    return int(migrations[-1].split('_')[0])


def reserve_migrations(base, number, git_add):
    last = get_last_migration(base)
    for i in range(last + 1, last + number + 1):
        name = '%03i_placeholder.py' % i
        path = os.path.join(*tuple(base + [name]))
        with open(path, 'w') as f:
            f.write(STUB)
        print('Created %s' % path)
        if git_add:
            subprocess.call('git add %s' % path, shell=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('-n', '--number', default=10,
                        type=int,
                        help='Number of migrations to reserve')
    parser.add_argument('-g', '--git-add', action='store_const',
                        const=True, default=False,
                        help='Automatically git-add new migrations')
    parser.add_argument('-a', '--api', action='store_const',
                        const=True, default=False,
                        help='Reserve migrations for the API database')
    args = parser.parse_args()
    if args.api:
        base = API_BASE
    else:
        base = BASE
    reserve_migrations(base, args.number, args.git_add)


if __name__ == '__main__':
    main()
