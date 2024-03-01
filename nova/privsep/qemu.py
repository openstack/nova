# Copyright 2018 Michael Still and Aptira
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
Helpers for qemu tasks.
"""

import contextlib
import os
import tempfile
import typing as ty

from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_utils import units

from nova import exception
from nova.i18n import _
import nova.privsep.utils

LOG = logging.getLogger(__name__)

QEMU_IMG_LIMITS = processutils.ProcessLimits(
    cpu_time=30,
    address_space=1 * units.Gi)


class EncryptionOptions(ty.TypedDict):
    secret: str
    format: str


@nova.privsep.sys_admin_pctxt.entrypoint
def convert_image(source, dest, in_format, out_format, instances_path,
                  compress, src_encryption=None, dest_encryption=None):
    unprivileged_convert_image(source, dest, in_format, out_format,
                               instances_path, compress,
                               src_encryption=src_encryption,
                               dest_encryption=dest_encryption)


# NOTE(mikal): this method is deliberately not wrapped in a privsep entrypoint
def unprivileged_convert_image(
    source: str,
    dest: str,
    in_format: ty.Optional[str],
    out_format: str,
    instances_path: str,
    compress: bool,
    src_encryption: ty.Optional[EncryptionOptions] = None,
    dest_encryption: ty.Optional[EncryptionOptions] = None,
) -> None:
    """Disk image conversion with qemu-img

    :param source: Location of the disk image to convert
    :param dest: Desired location of the converted disk image
    :param in_format: Disk image format of the source image
    :param out_format: Desired disk image format of the converted disk image
    :param instances_path: Location where instances are stored on disk
    :param compress: Whether to compress the converted disk image
    :param src_encryption: (Optional) Dict detailing various encryption
        attributes for the source image such as the format and passphrase.
    :param dest_encryption: (Optional) Dict detailing various encryption
        attributes for the destination image such as the format and passphrase.

    The in_format and out_format represent disk image file formats in QEMU,
    which are:

        * qcow2, which can be encrypted or not encrypted depending on options
        * raw, which is unencrypted
        * luks, which is encrypted raw

    See https://www.qemu.org/docs/master/system/qemu-block-drivers.html
    """
    # NOTE(mdbooth, kchamart): `qemu-img convert` defaults to
    # 'cache=writeback' for the source image, and 'cache=unsafe' for the
    # target, which means that data is not synced to disk at completion.
    # We explicitly use 'cache=none' here, for the target image, to (1)
    # ensure that we don't interfere with other applications using the
    # host's I/O cache, and (2) ensure that the data is on persistent
    # storage when the command exits. Without (2), a host crash may
    # leave a corrupt image in the image cache, which Nova cannot
    # recover automatically.

    # NOTE(zigo, kchamart): We cannot use `qemu-img convert -t none` if
    # the 'instance_dir' is mounted on a filesystem that doesn't support
    # O_DIRECT, which is the case, for example, with 'tmpfs'. This
    # simply crashes `openstack server create` in environments like live
    # distributions. In such cases, the best choice is 'writeback',
    # which (a) makes the conversion multiple times faster; and (b) is
    # as safe as it can be, because at the end of the conversion it,
    # just like 'writethrough', calls fsync(2)|fdatasync(2), which
    # ensures to safely write the data to the physical disk.

    # NOTE(mikal): there is an assumption here that the source and destination
    # are in the instances_path. Is that worth enforcing?
    if nova.privsep.utils.supports_direct_io(instances_path):
        cache_mode = 'none'
    else:
        cache_mode = 'writeback'
    cmd = ['qemu-img', 'convert', '-t', cache_mode, '-O', out_format]

    # qemu-img: --image-opts and --format are mutually exclusive
    # If the source is encrypted, we will need to pass encryption related
    # options using --image-opts.
    driver_str = ''
    if in_format is not None:
        if not src_encryption:
            cmd += ['-f', in_format]
        else:
            driver_str = f'driver={in_format},'

    if compress:
        cmd += ['-c']

    src_secret_file = None
    dest_secret_file = None
    encryption_opts: ty.List[str] = []
    with contextlib.ExitStack() as stack:
        if src_encryption:
            src_secret_file = stack.enter_context(
                tempfile.NamedTemporaryFile(mode='tr+', encoding='utf-8'))

            # Write out the passphrase secret to a temp file
            src_secret_file.write(src_encryption['secret'])

            # Ensure the secret is written to disk, we can't .close() here as
            # that removes the file when using NamedTemporaryFile
            src_secret_file.flush()

            # When --image-opts is used, the source filename must be passed as
            # part of the option string instead of as a positional arg.
            #
            # The basic options include the secret and encryption format
            # Option names depend on the QEMU disk image file format:
            # https://www.qemu.org/docs/master/system/qemu-block-drivers.html#disk-image-file-formats # noqa
            # For 'luks' it is 'key-secret' and format is implied
            # For 'qcow2' it is 'encrypt.key-secret' and 'encrypt.format'
            prefix = 'encrypt.' if in_format == 'qcow2' else ''
            encryption_opts = [
                '--object', f"secret,id=sec0,file={src_secret_file.name}",
                '--image-opts',
                f"{driver_str}file.driver=file,file.filename={source},"
                f"{prefix}key-secret=sec0",
            ]

        if dest_encryption:
            dest_secret_file = stack.enter_context(
                tempfile.NamedTemporaryFile(mode='tr+', encoding='utf-8'))

            # Write out the passphrase secret to a temp file
            dest_secret_file.write(dest_encryption['secret'])

            # Ensure the secret is written to disk, we can't .close()
            # here as that removes the file when using
            # NamedTemporaryFile
            dest_secret_file.flush()

            prefix = 'encrypt.' if out_format == 'qcow2' else ''
            encryption_opts += [
                '--object', f"secret,id=sec1,file={dest_secret_file.name}",
                '-o', f'{prefix}key-secret=sec1',
            ]
            if prefix:
                # The encryption format is only relevant for the 'qcow2' disk
                # format. Otherwise, the disk format is 'luks' and the
                # encryption format is implied and not accepted as an option in
                # that case.
                encryption_opts += [
                    '-o', f"{prefix}format={dest_encryption['format']}"
                ]
            # Supported luks options:
            #  cipher-alg=<str>       - Name of cipher algorithm and
            #                           key length
            #  cipher-mode=<str>      - Name of encryption cipher mode
            #  hash-alg=<str>         - Name of hash algorithm to use
            #                           for PBKDF
            #  iter-time=<num>        - Time to spend in PBKDF in
            #                           milliseconds
            #  ivgen-alg=<str>        - Name of IV generator algorithm
            #  ivgen-hash-alg=<str>   - Name of IV generator hash
            #                           algorithm
            #
            # NOTE(melwitt): Sensible defaults (that match the qemu
            # defaults) are hardcoded at this time for simplicity and
            # consistency when instances are migrated. Configuration of
            # luks options could be added in a future release.
            encryption_options = {
                'cipher-alg': 'aes-256',
                'cipher-mode': 'xts',
                'hash-alg': 'sha256',
                'iter-time': 2000,
                'ivgen-alg': 'plain64',
                'ivgen-hash-alg': 'sha256',
            }
            for option, value in encryption_options.items():
                encryption_opts += [
                    '-o', f'{prefix}{option}={value}',
                ]

        if src_encryption or dest_encryption:
            cmd += encryption_opts

        # If the source is not encrypted, it's passed as a positional argument.
        if not src_encryption:
            cmd += [source]

        processutils.execute(*cmd + [dest])


@nova.privsep.sys_admin_pctxt.entrypoint
def privileged_qemu_img_info(path, format=None):
    """Return an object containing the parsed output from qemu-img info

    This is a privileged call to qemu-img info using the sys_admin_pctxt
    entrypoint allowing host block devices etc to be accessed.
    """
    return unprivileged_qemu_img_info(path, format=format)


def unprivileged_qemu_img_info(path, format=None):
    """Return an object containing the parsed output from qemu-img info."""
    try:
        # The following check is about ploop images that reside within
        # directories and always have DiskDescriptor.xml file beside them
        if (os.path.isdir(path) and
            os.path.exists(os.path.join(path, "DiskDescriptor.xml"))):
            path = os.path.join(path, "root.hds")

        cmd = [
            'env', 'LC_ALL=C', 'LANG=C', 'qemu-img', 'info', path,
            '--force-share', '--output=json',
            ]
        if format is not None:
            cmd = cmd + ['-f', format]
        out, err = processutils.execute(*cmd, prlimit=QEMU_IMG_LIMITS)
    except processutils.ProcessExecutionError as exp:
        if exp.exit_code == -9:
            # this means we hit prlimits, make the exception more specific
            msg = (_("qemu-img aborted by prlimits when inspecting "
                    "%(path)s : %(exp)s") % {'path': path, 'exp': exp})
        elif exp.exit_code == 1 and 'No such file or directory' in exp.stderr:
            # The os.path.exists check above can race so this is a simple
            # best effort at catching that type of failure and raising a more
            # specific error.
            raise exception.DiskNotFound(location=path)
        else:
            msg = (_("qemu-img failed to execute on %(path)s : %(exp)s") %
                   {'path': path, 'exp': exp})
        raise exception.InvalidDiskInfo(reason=msg)

    if not out:
        msg = (_("Failed to run qemu-img info on %(path)s : %(error)s") %
               {'path': path, 'error': err})
        raise exception.InvalidDiskInfo(reason=msg)
    return out
