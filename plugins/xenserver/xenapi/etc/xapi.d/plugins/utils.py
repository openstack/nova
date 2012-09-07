# Copyright (c) 2012 OpenStack, LLC
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

"""Various utilities used by XenServer plugins."""

import cPickle as pickle
import logging
import os
import shlex
import shutil
import subprocess
import tempfile

import XenAPIPlugin

CHUNK_SIZE = 8192


def _link(src, dst):
    logging.info("Hard-linking file '%s' -> '%s'" % (src, dst))
    os.link(src, dst)


def _rename(src, dst):
    logging.info("Renaming file '%s' -> '%s'" % (src, dst))
    os.rename(src, dst)


def make_subprocess(cmdline, stdout=False, stderr=False, stdin=False):
    """Make a subprocess according to the given command-line string
    """
    # NOTE(dprince): shlex python 2.4 doesn't like unicode so we
    # explicitly convert to ascii
    cmdline = cmdline.encode('ascii')
    logging.info("Running cmd '%s'" % cmdline)
    kwargs = {}
    kwargs['stdout'] = stdout and subprocess.PIPE or None
    kwargs['stderr'] = stderr and subprocess.PIPE or None
    kwargs['stdin'] = stdin and subprocess.PIPE or None
    args = shlex.split(cmdline)
    logging.info("Running args '%s'" % args)
    proc = subprocess.Popen(args, **kwargs)
    return proc


def finish_subprocess(proc, cmdline, ok_exit_codes=None):
    """Ensure that the process returned a zero exit code indicating success
    """
    if ok_exit_codes is None:
        ok_exit_codes = [0]

    out, err = proc.communicate()
    ret = proc.returncode
    if ret not in ok_exit_codes:
        raise Exception("'%(cmdline)s' returned non-zero exit code: "
                        "retcode=%(ret)i, out='%(out)s', stderr='%(err)s'"
                        % locals())
    return out, err


def make_staging_area(sr_path):
    """
    The staging area is a place where we can temporarily store and
    manipulate VHDs. The use of the staging area is different for upload and
    download:

    Download
    ========

    When we download the tarball, the VHDs contained within will have names
    like "snap.vhd" and "image.vhd". We need to assign UUIDs to them before
    moving them into the SR. However, since 'image.vhd' may be a base_copy, we
    need to link it to 'snap.vhd' (using vhd-util modify) before moving both
    into the SR (otherwise the SR.scan will cause 'image.vhd' to be deleted).
    The staging area gives us a place to perform these operations before they
    are moved to the SR, scanned, and then registered with XenServer.

    Upload
    ======

    On upload, we want to rename the VHDs to reflect what they are, 'snap.vhd'
    in the case of the snapshot VHD, and 'image.vhd' in the case of the
    base_copy. The staging area provides a directory in which we can create
    hard-links to rename the VHDs without affecting what's in the SR.


    NOTE
    ====

    The staging area is created as a subdirectory within the SR in order to
    guarantee that it resides within the same filesystem and therefore permit
    hard-linking and cheap file moves.
    """
    staging_path = tempfile.mkdtemp(dir=sr_path)
    return staging_path


def cleanup_staging_area(staging_path):
    """Remove staging area directory

    On upload, the staging area contains hard-links to the VHDs in the SR;
    it's safe to remove the staging-area because the SR will keep the link
    count > 0 (so the VHDs in the SR will not be deleted).
    """
    if os.path.exists(staging_path):
        shutil.rmtree(staging_path)


def _handle_old_style_images(staging_path):
    """Rename files to conform to new image format, if needed.

    Old-Style:

        snap.vhd -> image.vhd -> base.vhd

    New-Style:

        0.vhd -> 1.vhd -> ... (n-1).vhd

    The New-Style format has the benefit of being able to support a VDI chain
    of arbitrary length.
    """
    file_num = 0
    for filename in ('snap.vhd', 'image.vhd', 'base.vhd'):
        path = os.path.join(staging_path, filename)
        if os.path.exists(path):
            _rename(path, os.path.join(staging_path, "%d.vhd" % file_num))
            file_num += 1


def _assert_vhd_not_hidden(path):
    """Sanity check to ensure that only appropriate VHDs are marked as hidden.

    If this flag is incorrectly set, then when we move the VHD into the SR, it
    will be deleted out from under us.
    """
    query_cmd = "vhd-util query -n %(path)s -f" % locals()
    query_proc = make_subprocess(query_cmd, stdout=True, stderr=True)
    out, err = finish_subprocess(query_proc, query_cmd)

    for line in out.splitlines():
        if line.startswith('hidden'):
            value = line.split(':')[1].strip()
            if value == "1":
                raise Exception(
                    "VHD %(path)s is marked as hidden without child" %
                    locals())


def _validate_footer_timestamp(vdi_path):
    """
    This check ensures that the timestamps listed in the VHD footer aren't in
    the future.  This can occur during a migration if the clocks on the the two
    Dom0's are out-of-sync. This would corrupt the SR if it were imported, so
    generate an exception to bail.
    """
    check_cmd = "vhd-util check -n %(vdi_path)s -p" % locals()
    check_proc = make_subprocess(check_cmd, stdout=True, stderr=True)
    out, err = finish_subprocess(
            check_proc, check_cmd, ok_exit_codes=[0, 22])
    first_line = out.splitlines()[0].strip()

    if 'primary footer invalid' in first_line:
        raise Exception("VDI '%(vdi_path)s' has timestamp in the future,"
                        " ensure source and destination host machines have"
                        " time set correctly" % locals())
    elif check_proc.returncode != 0:
        raise Exception("Unexpected output '%(out)s' from vhd-util" %
                        locals())


def _validate_vdi_chain(vdi_path):
    """
    This check ensures that the parent pointers on the VHDs are valid
    before we move the VDI chain to the SR. This is *very* important
    because a bad parent pointer will corrupt the SR causing a cascade of
    failures.
    """
    def get_parent_path(path):
        query_cmd = "vhd-util query -n %(path)s -p" % locals()
        query_proc = make_subprocess(query_cmd, stdout=True, stderr=True)
        out, err = finish_subprocess(
                query_proc, query_cmd, ok_exit_codes=[0, 22])
        first_line = out.splitlines()[0].strip()

        if first_line.endswith(".vhd"):
            return first_line
        elif 'has no parent' in first_line:
            return None
        elif 'query failed' in first_line:
            raise Exception("VDI '%(path)s' not present which breaks"
                            " the VDI chain, bailing out" % locals())
        else:
            raise Exception("Unexpected output '%(out)s' from vhd-util" %
                            locals())

    cur_path = vdi_path
    while cur_path:
        _validate_footer_timestamp(cur_path)
        cur_path = get_parent_path(cur_path)


def _validate_sequenced_vhds(staging_path):
    """This check ensures that the VHDs in the staging area are sequenced
    properly from 0 to n-1 with no gaps.
    """
    seq_num = 0
    filenames = os.listdir(staging_path)
    for filename in filenames:
        if not filename.endswith('.vhd'):
            continue

        if filename == "swap.vhd":
            continue

        vhd_path = os.path.join(staging_path, "%d.vhd" % seq_num)
        if not os.path.exists(vhd_path):
            raise Exception("Corrupt image. Expected seq number: %d. Files: %s"
                            % (seq_num, filenames))

        seq_num += 1


def import_vhds(sr_path, staging_path, uuid_stack):
    """Move VHDs from staging area into the SR.

    The staging area is necessary because we need to perform some fixups
    (assigning UUIDs, relinking the VHD chain) before moving into the SR,
    otherwise the SR manager process could potentially delete the VHDs out from
    under us.

    Returns: A dict of imported VHDs:

        {'root': {'uuid': 'ffff-aaaa'},
         'swap': {'uuid': 'ffff-bbbb'}}
    """
    _handle_old_style_images(staging_path)
    _validate_sequenced_vhds(staging_path)

    imported_vhds = {}
    files_to_move = []

    # Collect sequenced VHDs and assign UUIDs to them
    seq_num = 0
    while True:
        orig_vhd_path = os.path.join(staging_path, "%d.vhd" % seq_num)
        if not os.path.exists(orig_vhd_path):
            break

        # Rename (0, 1 .. N).vhd -> aaaa-bbbb-cccc-dddd.vhd
        vhd_uuid = uuid_stack.pop()
        vhd_path = os.path.join(staging_path, "%s.vhd" % vhd_uuid)
        _rename(orig_vhd_path, vhd_path)

        if seq_num == 0:
            leaf_vhd_path = vhd_path
            leaf_vhd_uuid = vhd_uuid

        files_to_move.append(vhd_path)
        seq_num += 1

    # Re-link VHDs, in reverse order, from base-copy -> leaf
    parent_path = None
    for vhd_path in reversed(files_to_move):
        if parent_path:
            # Link to parent
            modify_cmd = ("vhd-util modify -n %(vhd_path)s"
                          " -p %(parent_path)s" % locals())
            modify_proc = make_subprocess(modify_cmd, stderr=True)
            finish_subprocess(modify_proc, modify_cmd)

        parent_path = vhd_path

    # Sanity check the leaf VHD
    _assert_vhd_not_hidden(leaf_vhd_path)
    _validate_vdi_chain(leaf_vhd_path)

    imported_vhds["root"] = {"uuid": leaf_vhd_uuid}

    # Handle swap file if present
    orig_swap_path = os.path.join(staging_path, "swap.vhd")
    if os.path.exists(orig_swap_path):
        # Rename swap.vhd -> aaaa-bbbb-cccc-dddd.vhd
        vhd_uuid = uuid_stack.pop()
        swap_path = os.path.join(staging_path, "%s.vhd" % vhd_uuid)
        _rename(orig_swap_path, swap_path)

        _assert_vhd_not_hidden(swap_path)

        imported_vhds["swap"] = {"uuid": vhd_uuid}
        files_to_move.append(swap_path)

    # Move files into SR
    for orig_path in files_to_move:
        new_path = os.path.join(sr_path, os.path.basename(orig_path))
        _rename(orig_path, new_path)

    return imported_vhds


def prepare_staging_area(sr_path, staging_path, vdi_uuids, seq_num=0):
    """Hard-link VHDs into staging area."""
    for vdi_uuid in vdi_uuids:
        source = os.path.join(sr_path, "%s.vhd" % vdi_uuid)
        link_name = os.path.join(staging_path, "%d.vhd" % seq_num)
        _link(source, link_name)
        seq_num += 1


def create_tarball(fileobj, path, callback=None):
    """Create a tarball from a given path.

    :param fileobj: a file-like object holding the tarball byte-stream.
                    If None, then only the callback will be used.
    :param path: path to create tarball from
    :param callback: optional callback to call on each chunk written
    """
    tar_cmd = "tar -zc --directory=%(path)s ." % locals()
    tar_proc = make_subprocess(tar_cmd, stdout=True, stderr=True)

    while True:
        chunk = tar_proc.stdout.read(CHUNK_SIZE)
        if chunk == '':
            break

        if callback:
            callback(chunk)

        if fileobj:
            fileobj.write(chunk)

    finish_subprocess(tar_proc, tar_cmd)


def extract_tarball(fileobj, path, callback=None):
    """Extract a tarball to a given path.

    :param fileobj: a file-like object holding the tarball byte-stream
    :param path: path to extract tarball into
    :param callback: optional callback to call on each chunk read
    """
    tar_cmd = "tar -zx --directory=%(path)s" % locals()
    tar_proc = make_subprocess(tar_cmd, stderr=True, stdin=True)

    while True:
        chunk = fileobj.read(CHUNK_SIZE)
        if chunk == '':
            break

        if callback:
            callback(chunk)

        tar_proc.stdin.write(chunk)

    finish_subprocess(tar_proc, tar_cmd)


def _handle_serialization(func):
    def wrapped(session, params):
        params = pickle.loads(params['params'])
        rv = func(session, *params['args'], **params['kwargs'])
        return pickle.dumps(rv)
    return wrapped


def register_plugin_calls(*funcs):
    """Wrapper around XenAPIPlugin.dispatch which handles pickle
    serialization.
    """
    wrapped_dict = {}
    for func in funcs:
        wrapped_dict[func.__name__] = _handle_serialization(func)
    XenAPIPlugin.dispatch(wrapped_dict)
