# Copyright (c) 2012 Openstack, LLC
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

import logging
import os
import shlex
import shutil
import subprocess
import tempfile


CHUNK_SIZE = 8192


def make_subprocess(cmdline, stdout=False, stderr=False, stdin=False):
    """Make a subprocess according to the given command-line string
    """
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


def import_vhds(sr_path, staging_path, uuid_stack):
    """Import the VHDs found in the staging path.

    We cannot extract VHDs directly into the SR since they don't yet have
    UUIDs, aren't properly associated with each other, and would be subject to
    a race-condition of one-file being present and the other not being
    downloaded yet.

    To avoid these we problems, we use a staging area to fixup the VHDs before
    moving them into the SR. The steps involved are:

        1. Extracting tarball into staging area (done prior to this call)

        2. Renaming VHDs to use UUIDs ('snap.vhd' -> 'ffff-aaaa-...vhd')

        3. Linking VHDs together if there's a snap.vhd

        4. Pseudo-atomically moving the images into the SR. (It's not really
           atomic because it takes place as multiple os.rename operations;
           however, the chances of an SR.scan occuring between the rename()s
           invocations is so small that we can safely ignore it)

    Returns: A dict of the VDIs imported. For example:

        {'root': {'uuid': 'ffff-aaaa'},
         'swap': {'uuid': 'ffff-bbbb'}}
    """
    def rename_with_uuid(orig_path):
        """Rename VHD using UUID so that it will be recognized by SR on a
        subsequent scan.

        Since Python2.4 doesn't have the `uuid` module, we pass a stack of
        pre-computed UUIDs from the compute worker.
        """
        orig_dirname = os.path.dirname(orig_path)
        uuid = uuid_stack.pop()
        new_path = os.path.join(orig_dirname, "%s.vhd" % uuid)
        os.rename(orig_path, new_path)
        return new_path, uuid

    def link_vhds(child_path, parent_path):
        """Use vhd-util to associate the snapshot VHD with its base_copy.

        This needs to be done before we move both VHDs into the SR to prevent
        the base_copy from being DOA (deleted-on-arrival).
        """
        modify_cmd = ("vhd-util modify -n %(child_path)s -p %(parent_path)s"
                      % locals())
        modify_proc = make_subprocess(modify_cmd, stderr=True)
        finish_subprocess(modify_proc, modify_cmd)

    def move_into_sr(orig_path):
        """Move a file into the SR"""
        filename = os.path.basename(orig_path)
        new_path = os.path.join(sr_path, filename)
        os.rename(orig_path, new_path)
        return new_path

    def assert_vhd_not_hidden(path):
        """
        This is a sanity check on the image; if a snap.vhd isn't
        present, then the image.vhd better not be marked 'hidden' or it will
        be deleted when moved into the SR.
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

    def prepare_if_exists(staging_path, vhd_name, parent_path=None):
        """
        Check for existance of a particular VHD in the staging path and
        preparing it for moving into the SR.

        Returns: Tuple of (Path to move into the SR, VDI_UUID)
                 None, if the vhd_name doesn't exist in the staging path

        If the VHD exists, we will do the following:
            1. Rename it with a UUID.
            2. If parent_path exists, we'll link up the VHDs.
        """
        orig_path = os.path.join(staging_path, vhd_name)
        if not os.path.exists(orig_path):
            return None
        new_path, vdi_uuid = rename_with_uuid(orig_path)
        if parent_path:
            # NOTE(sirp): this step is necessary so that an SR scan won't
            # delete the base_copy out from under us (since it would be
            # orphaned)
            link_vhds(new_path, parent_path)
        return (new_path, vdi_uuid)

    def validate_vdi_chain(vdi_path):
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
            cur_path = get_parent_path(cur_path)

    imported_vhds = {}
    paths_to_move = []

    image_parent = None
    base_info = prepare_if_exists(staging_path, 'base.vhd')
    if base_info:
        paths_to_move.append(base_info[0])
        image_parent = base_info[0]

    image_info = prepare_if_exists(staging_path, 'image.vhd', image_parent)
    if not image_info:
        raise Exception("Invalid image: image.vhd not present")

    paths_to_move.insert(0, image_info[0])

    snap_info = prepare_if_exists(staging_path, 'snap.vhd',
            image_info[0])
    if snap_info:
        validate_vdi_chain(snap_info[0])
        # NOTE(sirp): this is an insert rather than an append since the
        # 'snapshot' vhd needs to be copied into the SR before the base copy.
        # If it doesn't, then there is a possibliity that snapwatchd will
        # delete the base_copy since it is an unreferenced parent.
        paths_to_move.insert(0, snap_info[0])
        # We return this snap as the VDI instead of image.vhd
        imported_vhds['root'] = dict(uuid=snap_info[1])
    else:
        validate_vdi_chain(image_info[0])
        assert_vhd_not_hidden(image_info[0])
        # If there's no snap, we return the image.vhd UUID
        imported_vhds['root'] = dict(uuid=image_info[1])

    swap_info = prepare_if_exists(staging_path, 'swap.vhd')
    if swap_info:
        assert_vhd_not_hidden(swap_info[0])
        paths_to_move.append(swap_info[0])
        imported_vhds['swap'] = dict(uuid=swap_info[1])

    for path in paths_to_move:
        move_into_sr(path)

    return imported_vhds


def prepare_staging_area_for_upload(sr_path, staging_path, vdi_uuids):
    """Hard-link VHDs into staging area with appropriate filename
    ('snap' or 'image.vhd')
    """
    for name, uuid in vdi_uuids.items():
        if uuid:
            source = os.path.join(sr_path, "%s.vhd" % uuid)
            link_name = os.path.join(staging_path, "%s.vhd" % name)
            os.link(source, link_name)


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
