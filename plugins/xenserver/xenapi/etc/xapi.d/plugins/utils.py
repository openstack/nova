# Copyright (c) 2012 OpenStack Foundation
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

# NOTE: XenServer still only supports Python 2.4 in it's dom0 userspace
# which means the Nova xenapi plugins must use only Python 2.4 features

"""Various utilities used by XenServer plugins."""

import cPickle as pickle
import errno
import logging
import os
import shutil
import signal
import subprocess
import tempfile

import XenAPIPlugin

LOG = logging.getLogger(__name__)
CHUNK_SIZE = 8192


class CommandNotFound(Exception):
    pass


def delete_if_exists(path):
    try:
        os.unlink(path)
    except OSError, e:  # noqa
        if e.errno == errno.ENOENT:
            LOG.warning("'%s' was already deleted, skipping delete" % path)
        else:
            raise


def _link(src, dst):
    LOG.info("Hard-linking file '%s' -> '%s'" % (src, dst))
    os.link(src, dst)


def _rename(src, dst):
    LOG.info("Renaming file '%s' -> '%s'" % (src, dst))
    try:
        os.rename(src, dst)
    except OSError, e:  # noqa
        if e.errno == errno.EXDEV:
            LOG.error("Invalid cross-device link.  Perhaps %s and %s should "
                      "be symlinked on the same filesystem?" % (src, dst))
        raise


def make_subprocess(cmdline, stdout=False, stderr=False, stdin=False,
                    universal_newlines=False, close_fds=True, env=None):
    """Make a subprocess according to the given command-line string
    """
    LOG.info("Running cmd '%s'" % " ".join(cmdline))
    kwargs = {}
    kwargs['stdout'] = stdout and subprocess.PIPE or None
    kwargs['stderr'] = stderr and subprocess.PIPE or None
    kwargs['stdin'] = stdin and subprocess.PIPE or None
    kwargs['universal_newlines'] = universal_newlines
    kwargs['close_fds'] = close_fds
    kwargs['env'] = env
    try:
        proc = subprocess.Popen(cmdline, **kwargs)
    except OSError, e:  # noqa
        if e.errno == errno.ENOENT:
            raise CommandNotFound
        else:
            raise
    return proc


class SubprocessException(Exception):
    def __init__(self, cmdline, ret, out, err):
        Exception.__init__(self, "'%s' returned non-zero exit code: "
                           "retcode=%i, out='%s', stderr='%s'"
                           % (cmdline, ret, out, err))
        self.cmdline = cmdline
        self.ret = ret
        self.out = out
        self.err = err


def finish_subprocess(proc, cmdline, cmd_input=None, ok_exit_codes=None):
    """Ensure that the process returned a zero exit code indicating success
    """
    if ok_exit_codes is None:
        ok_exit_codes = [0]
    out, err = proc.communicate(cmd_input)

    ret = proc.returncode
    if ret not in ok_exit_codes:
        LOG.error("Command '%(cmdline)s' with process id '%(pid)s' expected "
                  "return code in '%(ok)s' but got '%(rc)s': %(err)s" %
                  {'cmdline': cmdline, 'pid': proc.pid, 'ok': ok_exit_codes,
                   'rc': ret, 'err': err})
        raise SubprocessException(' '.join(cmdline), ret, out, err)
    return out


def run_command(cmd, cmd_input=None, ok_exit_codes=None):
    """Abstracts out the basics of issuing system commands. If the command
    returns anything in stderr, an exception is raised with that information.
    Otherwise, the output from stdout is returned.

    cmd_input is passed to the process on standard input.
    """
    proc = make_subprocess(cmd, stdout=True, stderr=True, stdin=True,
                           close_fds=True)
    return finish_subprocess(proc, cmd, cmd_input=cmd_input,
                             ok_exit_codes=ok_exit_codes)


def try_kill_process(proc):
    """Sends the given process the SIGKILL signal."""
    pid = proc.pid
    LOG.info("Killing process %s" % pid)
    try:
        os.kill(pid, signal.SIGKILL)
    except Exception:
        LOG.exception("Failed to kill %s" % pid)


def make_staging_area(sr_path):
    """The staging area is a place where we can temporarily store and
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
    query_cmd = ["vhd-util", "query", "-n", path, "-f"]
    out = run_command(query_cmd)

    for line in out.splitlines():
        if line.lower().startswith('hidden'):
            value = line.split(':')[1].strip()
            if value == "1":
                raise Exception(
                    "VHD %s is marked as hidden without child" % path)


def _vhd_util_check(vdi_path):
    check_cmd = ["vhd-util", "check", "-n", vdi_path, "-p"]
    out = run_command(check_cmd, ok_exit_codes=[0, 22])
    first_line = out.splitlines()[0].strip()
    return out, first_line


def _validate_vhd(vdi_path):
    """This checks for several errors in the VHD structure.

    Most notably, it checks that the timestamp in the footer is correct, but
    may pick up other errors also.

    This check ensures that the timestamps listed in the VHD footer aren't in
    the future.  This can occur during a migration if the clocks on the two
    Dom0's are out-of-sync. This would corrupt the SR if it were imported, so
    generate an exception to bail.
    """
    out, first_line = _vhd_util_check(vdi_path)

    if 'invalid' in first_line:
        LOG.warning("VHD invalid, attempting repair.")
        repair_cmd = ["vhd-util", "repair", "-n", vdi_path]
        run_command(repair_cmd)
        out, first_line = _vhd_util_check(vdi_path)

    if 'invalid' in first_line:
        if 'footer' in first_line:
            part = 'footer'
        elif 'header' in first_line:
            part = 'header'
        else:
            part = 'setting'

        details = first_line.split(':', 1)
        if len(details) == 2:
            details = details[1]
        else:
            details = first_line

        extra = ''
        if 'timestamp' in first_line:
            extra = (" ensure source and destination host machines have "
                     "time set correctly")

        LOG.info("VDI Error details: %s" % out)

        raise Exception(
            "VDI '%(vdi_path)s' has an invalid %(part)s: '%(details)s'"
            "%(extra)s" % {'vdi_path': vdi_path, 'part': part,
                           'details': details, 'extra': extra})

    LOG.info("VDI is valid: %s" % vdi_path)


def _validate_vdi_chain(vdi_path):
    """This check ensures that the parent pointers on the VHDs are valid
    before we move the VDI chain to the SR. This is *very* important
    because a bad parent pointer will corrupt the SR causing a cascade of
    failures.
    """
    def get_parent_path(path):
        query_cmd = ["vhd-util", "query", "-n", path, "-p"]
        out = run_command(query_cmd, ok_exit_codes=[0, 22])
        first_line = out.splitlines()[0].strip()

        if first_line.endswith(".vhd"):
            return first_line
        elif 'has no parent' in first_line:
            return None
        elif 'query failed' in first_line:
            raise Exception("VDI '%s' not present which breaks"
                            " the VDI chain, bailing out" % path)
        else:
            raise Exception("Unexpected output '%s' from vhd-util" % out)

    cur_path = vdi_path
    while cur_path:
        _validate_vhd(cur_path)
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

        # Ignore legacy swap embedded in the image, generated on-the-fly now
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

        {'root': {'uuid': 'ffff-aaaa'}}
    """
    _handle_old_style_images(staging_path)
    _validate_sequenced_vhds(staging_path)

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
            modify_cmd = ["vhd-util", "modify", "-n", vhd_path,
                          "-p", parent_path]
            run_command(modify_cmd)

        parent_path = vhd_path

    # Sanity check the leaf VHD
    _assert_vhd_not_hidden(leaf_vhd_path)
    _validate_vdi_chain(leaf_vhd_path)

    # Move files into SR
    for orig_path in files_to_move:
        new_path = os.path.join(sr_path, os.path.basename(orig_path))
        _rename(orig_path, new_path)

    imported_vhds = dict(root=dict(uuid=leaf_vhd_uuid))
    return imported_vhds


def prepare_staging_area(sr_path, staging_path, vdi_uuids, seq_num=0):
    """Hard-link VHDs into staging area."""
    for vdi_uuid in vdi_uuids:
        source = os.path.join(sr_path, "%s.vhd" % vdi_uuid)
        link_name = os.path.join(staging_path, "%d.vhd" % seq_num)
        _link(source, link_name)
        seq_num += 1


def create_tarball(fileobj, path, callback=None, compression_level=None):
    """Create a tarball from a given path.

    :param fileobj: a file-like object holding the tarball byte-stream.
                    If None, then only the callback will be used.
    :param path: path to create tarball from
    :param callback: optional callback to call on each chunk written
    :param compression_level: compression level, e.g., 9 for gzip -9.
    """
    tar_cmd = ["tar", "-zc", "--directory=%s" % path, "."]
    env = os.environ.copy()
    if compression_level and 1 <= compression_level <= 9:
        env["GZIP"] = "-%d" % compression_level
    tar_proc = make_subprocess(tar_cmd, stdout=True, stderr=True, env=env)

    try:
        while True:
            chunk = tar_proc.stdout.read(CHUNK_SIZE)
            if chunk == '':
                break

            if callback:
                callback(chunk)

            if fileobj:
                fileobj.write(chunk)
    except Exception:
        try_kill_process(tar_proc)
        raise

    finish_subprocess(tar_proc, tar_cmd)


def extract_tarball(fileobj, path, callback=None):
    """Extract a tarball to a given path.

    :param fileobj: a file-like object holding the tarball byte-stream
    :param path: path to extract tarball into
    :param callback: optional callback to call on each chunk read
    """
    tar_cmd = ["tar", "-zx", "--directory=%s" % path]
    tar_proc = make_subprocess(tar_cmd, stderr=True, stdin=True)

    try:
        while True:
            chunk = fileobj.read(CHUNK_SIZE)
            if chunk == '':
                break

            if callback:
                callback(chunk)

            tar_proc.stdin.write(chunk)
    except Exception:
        try_kill_process(tar_proc)
        raise

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
