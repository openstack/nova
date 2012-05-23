#!/usr/bin/env python

# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack LLC.
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
Utility for ensuring DB schemas don't change when compacting migrations.

Each release cycle the plan is to compact all of the migrations from that
release into a single file. This is a manual and, unfortunately, error-prone
process. To ensure that the schema doesn't change, this tool can be used to
diff the compacted DB schema to the original, uncompacted form.

Notes:

This utility assumes you start off in the branch containing the compacted
migration.

Run like:

    ./tools/db/validate_compacted_migration.py mysql 82 master
"""
import os
import subprocess
import sys

### Dump


def dump_db(db_driver, db_name, compacted_version, dump_filename,
            latest=False):
    db_driver.create(db_name)
    try:
        migrate(db_driver, db_name, compacted_version, latest=latest)
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
        return 'postgres://localhost/%s' % name


def _get_db_driver_class(db_type):
    if db_type == "mysql":
        return MySQL
    elif db_type == "postgres":
        return Postgres
    else:
        raise Exception("database %s not supported" % db_type)


### Migrate


def migrate(db_driver, db_name, compacted_version, latest=False):
    # NOTE(sirp): sqlalchemy-migrate currently cannot handle the skipping of
    # migration numbers
    _migrate_cmd(
            db_driver, db_name, 'version_control', str(compacted_version - 1))

    upgrade_cmd = ['upgrade']
    if not latest:
        upgrade_cmd.append(str(compacted_version))

    _migrate_cmd(db_driver, db_name, *upgrade_cmd)


def _migrate_cmd(db_driver, db_name, *cmd):
    MIGRATE_REPO = os.path.join(os.getcwd(), "nova/db/sqlalchemy/migrate_repo")
    manage_py = os.path.join(MIGRATE_REPO, 'manage.py')

    args = ['python', manage_py]
    args += cmd
    args += ['--repository=%s' % MIGRATE_REPO,
             '--url=%s' % db_driver.url(db_name)]

    subprocess.check_call(args)


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
    print >> sys.stderr, "ERROR: %s" % msg
    sys.exit(1)


def usage(msg=None):
    if msg:
        print >> sys.stderr, "ERROR: %s" % msg

    prog = "validate_compacted_migration.py"
    args = ["<mysql|postgres>", "<compacted-version>",
             "<uncompacted-branch-name>"]

    print >> sys.stderr, "usage: %s %s" % (prog, ' '.join(args))
    sys.exit(1)


def parse_options():
    try:
        db_type = sys.argv[1]
    except IndexError:
        usage("must specify DB type")

    try:
        compacted_version = int(sys.argv[2])
    except IndexError:
        usage('must specify compacted migration version')
    except ValueError:
        usage('compacted version must be a number')

    try:
        uncompacted_branch_name = sys.argv[3]
    except IndexError:
        usage('must specify uncompacted branch name')

    return db_type, compacted_version, uncompacted_branch_name


def main():
    COMPACTED_DB = 'compacted'
    UNCOMPACTED_DB = 'uncompacted'

    COMPACTED_FILENAME = COMPACTED_DB + ".dump"
    UNCOMPACTED_FILENAME = UNCOMPACTED_DB + ".dump"

    db_type, compacted_version, uncompacted_branch_name = parse_options()

    # Since we're going to be switching branches, ensure user doesn't have any
    # uncommited changes
    if git_has_uncommited_changes():
        die("You have uncommited changes. Please commit them before running "
            "this command.")

    db_driver = _get_db_driver_class(db_type)()

    # Dump Compacted
    dump_db(db_driver, COMPACTED_DB, compacted_version, COMPACTED_FILENAME)

    # Dump Uncompacted
    original_branch_name = git_current_branch_name()
    git_checkout(uncompacted_branch_name)
    try:
        dump_db(db_driver, UNCOMPACTED_DB, compacted_version,
                UNCOMPACTED_FILENAME, latest=True)
    finally:
        git_checkout(original_branch_name)

    diff_files(UNCOMPACTED_FILENAME, COMPACTED_FILENAME)


if __name__ == "__main__":
    main()
