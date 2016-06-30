# Copyright 2014 Rackspace, Andrew Melton
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""
##########
IDMapShift
##########

IDMapShift is a tool that properly sets the ownership of a filesystem for use
with linux user namespaces.

=====
Usage
=====

    nova-idmapshift -i -u 0:10000:2000 -g 0:10000:2000 path

This command will idempotently shift `path` to proper ownership using
the provided uid and gid mappings.

=========
Arguments
=========

    nova-idmapshift -i -c -d -v
                    -u [[guest-uid:host-uid:count],...]
                    -g [[guest-gid:host-gid:count],...]
                    -n [nobody-id]
                    path

path: Root path of the filesystem to be shifted

-i, --idempotent: Shift operation will only be performed if filesystem
appears unshifted

-c, --confirm: Will perform check on filesystem
Returns 0 when filesystem appears shifted
Returns 1 when filesystem appears unshifted

-d, --dry-run: Print chown operations, but won't perform them

-v, --verbose: Print chown operations while performing them

-u, --uid: User ID mappings, maximum of 3 ranges

-g, --gid: Group ID mappings, maximum of 3 ranges

-n, --nobody: ID to map all unmapped uid and gids to.

=======
Purpose
=======

When using user namespaces with linux containers, the filesystem of the
container must be owned by the targeted user and group ids being applied
to that container. Otherwise, processes inside the container won't be able
to access the filesystem.

For example, when using the id map string '0:10000:2000', this means that
user ids inside the container between 0 and 1999 will map to user ids on
the host between 10000 and 11999. Root (0) becomes 10000, user 1 becomes
10001, user 50 becomes 10050 and user 1999 becomes 11999. This means that
files that are owned by root need to actually be owned by user 10000, and
files owned by 50 need to be owned by 10050, and so on.

IDMapShift will take the uid and gid strings used for user namespaces and
properly set up the filesystem for use by those users. Uids and gids outside
of provided ranges will be mapped to nobody (max uid/gid) so that they are
inaccessible inside the container.
"""


import argparse
import os
import sys

from nova.i18n import _

NOBODY_ID = 65534


def find_target_id(fsid, mappings, nobody, memo):
    if fsid not in memo:
        for start, target, count in mappings:
            if start <= fsid < start + count:
                memo[fsid] = (fsid - start) + target
                break
        else:
            memo[fsid] = nobody

    return memo[fsid]


def print_chown(path, uid, gid, target_uid, target_gid):
    print('%s %s:%s -> %s:%s' % (path, uid, gid, target_uid, target_gid))


def shift_path(path, uid_mappings, gid_mappings, nobody, uid_memo, gid_memo,
               dry_run=False, verbose=False):
    stat = os.lstat(path)
    uid = stat.st_uid
    gid = stat.st_gid
    target_uid = find_target_id(uid, uid_mappings, nobody, uid_memo)
    target_gid = find_target_id(gid, gid_mappings, nobody, gid_memo)
    if verbose:
        print_chown(path, uid, gid, target_uid, target_gid)
    if not dry_run:
        os.lchown(path, target_uid, target_gid)


def shift_dir(fsdir, uid_mappings, gid_mappings, nobody,
              dry_run=False, verbose=False):
    uid_memo = dict()
    gid_memo = dict()

    def shift_path_short(p):
        shift_path(p, uid_mappings, gid_mappings, nobody,
                   dry_run=dry_run, verbose=verbose,
                   uid_memo=uid_memo, gid_memo=gid_memo)

    shift_path_short(fsdir)
    for root, dirs, files in os.walk(fsdir):
        for d in dirs:
            path = os.path.join(root, d)
            shift_path_short(path)
        for f in files:
            path = os.path.join(root, f)
            shift_path_short(path)


def confirm_path(path, uid_ranges, gid_ranges, nobody):
    stat = os.lstat(path)
    uid = stat.st_uid
    gid = stat.st_gid

    uid_in_range = True if uid == nobody else False
    gid_in_range = True if gid == nobody else False

    if not uid_in_range or not gid_in_range:
        for (start, end) in uid_ranges:
            if start <= uid <= end:
                uid_in_range = True
                break

        for (start, end) in gid_ranges:
            if start <= gid <= end:
                gid_in_range = True
                break

    return uid_in_range and gid_in_range


def get_ranges(maps):
    return [(target, target + count - 1) for (start, target, count) in maps]


def confirm_dir(fsdir, uid_mappings, gid_mappings, nobody):
    uid_ranges = get_ranges(uid_mappings)
    gid_ranges = get_ranges(gid_mappings)

    if not confirm_path(fsdir, uid_ranges, gid_ranges, nobody):
        return False
    for root, dirs, files in os.walk(fsdir):
        for d in dirs:
            path = os.path.join(root, d)
            if not confirm_path(path, uid_ranges, gid_ranges, nobody):
                return False
        for f in files:
            path = os.path.join(root, f)
            if not confirm_path(path, uid_ranges, gid_ranges, nobody):
                return False
    return True


def id_map_type(val):
    maps = val.split(',')
    id_maps = []
    for m in maps:
        map_vals = m.split(':')

        if len(map_vals) != 3:
            msg = ('Invalid id map %s, correct syntax is '
                   'guest-id:host-id:count.')
            raise argparse.ArgumentTypeError(msg % val)

        try:
            vals = [int(i) for i in map_vals]
        except ValueError:
            msg = 'Invalid id map %s, values must be integers' % val
            raise argparse.ArgumentTypeError(msg)

        id_maps.append(tuple(vals))
    return id_maps


def main():
    parser = argparse.ArgumentParser(
                     description=_('nova-idmapshift is a tool that properly '
                                   'sets the ownership of a filesystem for '
                                   'use with linux user namespaces.  '
                                   'This tool can only be used with linux '
                                   'lxc containers.  See the man page for '
                                   'details.'))
    parser.add_argument('path')
    parser.add_argument('-u', '--uid', type=id_map_type, default=[])
    parser.add_argument('-g', '--gid', type=id_map_type, default=[])
    parser.add_argument('-n', '--nobody', default=NOBODY_ID, type=int)
    parser.add_argument('-i', '--idempotent', action='store_true')
    parser.add_argument('-c', '--confirm', action='store_true')
    parser.add_argument('-d', '--dry-run', action='store_true')
    parser.add_argument('-v', '--verbose', action='store_true')
    args = parser.parse_args()

    if args.idempotent or args.confirm:
        if confirm_dir(args.path, args.uid, args.gid, args.nobody):
            sys.exit(0)
        else:
            if args.confirm:
                sys.exit(1)

    shift_dir(args.path, args.uid, args.gid, args.nobody,
              dry_run=args.dry_run, verbose=args.verbose)
