#!/usr/bin/env python

# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

"""
Utility for diff'ing two versions of the DB schema.

Each release cycle the plan is to compact all of the migrations from that
release into a single file. This is a manual and, unfortunately, error-prone
process. To ensure that the schema doesn't change, this tool can be used to
diff the compacted DB schema to the original, uncompacted form.


The schema versions are specified by providing a git ref (a branch name or
commit hash) and a SQLAlchemy-Migrate version number:
Run like:

    ./tools/db/schema_diff.py mysql master:latest my_branch:82
"""

from __future__ import print_function

import datetime
import glob
import os
import subprocess
import sys

from nova.openstack.common.gettextutils import _


### Dump


def dump_db(db_driver, db_name, migration_version, dump_filename):
    db_driver.create(db_name)
    try:
        migrate(db_driver, db_name, migration_version)
        db_driver.dump(db_name, dump_filename)
    finally:
        db_driver.drop(db_name)


### Diff


def diff_files(filename1, filename2):
    pipeline = ['diff -U 3 %(filename1)s %(filename2)s' % locals()]

    # Use colordiff if available
    if subprocess.call(['which', 'colordiff']) == 0:
        pipeline.append('colordiff')

    pipeline.append('less -R')

    cmd = ' | '.join(pipeline)
    subprocess.check_call(cmd, shell=True)


### Database


class MySQL(object):
    def create(self, name):
        subprocess.check_call(['mysqladmin', '-u', 'root', 'create', name])

    def drop(self, name):
        subprocess.check_call(['mysqladmin', '-f', '-u', 'root', 'drop', name])

    def dump(self, name, dump_filename):
        subprocess.check_call(
                'mysqldump -u root %(name)s > %(dump_filename)s' % locals(),
                shell=True)

    def url(self, name):
        return 'mysql://root@localhost/%s' % name


class Postgres(object):
    def create(self, name):
        subprocess.check_call(['createdb', name])

    def drop(self, name):
        subprocess.check_call(['dropdb', name])

    def dump(self, name, dump_filename):
        subprocess.check_call(
                'pg_dump %(name)s > %(dump_filename)s' % locals(),
                shell=True)

    def url(self, name):
        return 'postgresql://localhost/%s' % name


def _get_db_driver_class(db_type):
    if db_type == "mysql":
        return MySQL
    elif db_type == "postgres":
        return Postgres
    else:
        raise Exception(_("database %s not supported") % db_type)


### Migrate


MIGRATE_REPO = os.path.join(os.getcwd(), "nova/db/sqlalchemy/migrate_repo")


def migrate(db_driver, db_name, migration_version):
    earliest_version = _migrate_get_earliest_version()

    # NOTE(sirp): sqlalchemy-migrate currently cannot handle the skipping of
    # migration numbers.
    _migrate_cmd(
            db_driver, db_name, 'version_control', str(earliest_version - 1))

    upgrade_cmd = ['upgrade']
    if migration_version != 'latest':
        upgrade_cmd.append(str(migration_version))

    _migrate_cmd(db_driver, db_name, *upgrade_cmd)


def _migrate_cmd(db_driver, db_name, *cmd):
    manage_py = os.path.join(MIGRATE_REPO, 'manage.py')

    args = ['python', manage_py]
    args += cmd
    args += ['--repository=%s' % MIGRATE_REPO,
             '--url=%s' % db_driver.url(db_name)]

    subprocess.check_call(args)


def _migrate_get_earliest_version():
    versions_glob = os.path.join(MIGRATE_REPO, 'versions', '???_*.py')

    versions = []
    for path in glob.iglob(versions_glob):
        filename = os.path.basename(path)
        prefix = filename.split('_', 1)[0]
        try:
            version = int(prefix)
        except ValueError:
            pass
        versions.append(version)

    versions.sort()
    return versions[0]


### Git


def git_current_branch_name():
    ref_name = git_symbolic_ref('HEAD', quiet=True)
    current_branch_name = ref_name.replace('refs/heads/', '')
    return current_branch_name


def git_symbolic_ref(ref, quiet=False):
    args = ['git', 'symbolic-ref', ref]
    if quiet:
        args.append('-q')
    proc = subprocess.Popen(args, stdout=subprocess.PIPE)
    stdout, stderr = proc.communicate()
    return stdout.strip()


def git_checkout(branch_name):
    subprocess.check_call(['git', 'checkout', branch_name])


def git_has_uncommited_changes():
    return subprocess.call(['git', 'diff', '--quiet', '--exit-code']) == 1


### Command


def die(msg):
    print("ERROR: %s" % msg, file=sys.stderr)
    sys.exit(1)


def usage(msg=None):
    if msg:
        print("ERROR: %s" % msg, file=sys.stderr)

    prog = "schema_diff.py"
    args = ["<mysql|postgres>", "<orig-branch:orig-version>",
            "<new-branch:new-version>"]

    print("usage: %s %s" % (prog, ' '.join(args)), file=sys.stderr)
    sys.exit(1)


def parse_options():
    try:
        db_type = sys.argv[1]
    except IndexError:
        usage("must specify DB type")

    try:
        orig_branch, orig_version = sys.argv[2].split(':')
    except IndexError:
        usage('original branch and version required (e.g. master:82)')

    try:
        new_branch, new_version = sys.argv[3].split(':')
    except IndexError:
        usage('new branch and version required (e.g. master:82)')

    return db_type, orig_branch, orig_version, new_branch, new_version


def main():
    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")

    ORIG_DB = 'orig_db_%s' % timestamp
    NEW_DB = 'new_db_%s' % timestamp

    ORIG_DUMP = ORIG_DB + ".dump"
    NEW_DUMP = NEW_DB + ".dump"

    options = parse_options()
    db_type, orig_branch, orig_version, new_branch, new_version = options

    # Since we're going to be switching branches, ensure user doesn't have any
    # uncommited changes
    if git_has_uncommited_changes():
        die("You have uncommited changes. Please commit them before running "
            "this command.")

    db_driver = _get_db_driver_class(db_type)()

    users_branch = git_current_branch_name()
    git_checkout(orig_branch)

    try:
        # Dump Original Schema
        dump_db(db_driver, ORIG_DB, orig_version, ORIG_DUMP)

        # Dump New Schema
        git_checkout(new_branch)
        dump_db(db_driver, NEW_DB, new_version, NEW_DUMP)

        diff_files(ORIG_DUMP, NEW_DUMP)
    finally:
        git_checkout(users_branch)

        if os.path.exists(ORIG_DUMP):
            os.unlink(ORIG_DUMP)

        if os.path.exists(NEW_DUMP):
            os.unlink(NEW_DUMP)


if __name__ == "__main__":
    main()
