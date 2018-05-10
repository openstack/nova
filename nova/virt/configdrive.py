# Copyright 2012 Michael Still and Canonical Inc
# All Rights Reserved.
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

"""Config Drive v2 helper."""

import os
import shutil

from oslo_concurrency import processutils
from oslo_utils import fileutils
from oslo_utils import units
import six

import nova.conf
from nova import exception
from nova.objects import fields
import nova.privsep.fs
from nova import utils
from nova import version

CONF = nova.conf.CONF

# Config drives are 64mb, if we can't size to the exact size of the data
CONFIGDRIVESIZE_BYTES = 64 * units.Mi


class ConfigDriveBuilder(object):
    """Build config drives, optionally as a context manager."""

    def __init__(self, instance_md=None):
        self.imagefile = None
        self.mdfiles = []

        if instance_md is not None:
            self.add_instance_metadata(instance_md)

    def __enter__(self):
        return self

    def __exit__(self, exctype, excval, exctb):
        if exctype is not None:
            # NOTE(mikal): this means we're being cleaned up because an
            # exception was thrown. All bets are off now, and we should not
            # swallow the exception
            return False
        self.cleanup()

    def _add_file(self, basedir, path, data):
        filepath = os.path.join(basedir, path)
        dirname = os.path.dirname(filepath)
        fileutils.ensure_tree(dirname)
        with open(filepath, 'wb') as f:
            # the given data can be either text or bytes. we can only write
            # bytes into files.
            if isinstance(data, six.text_type):
                data = data.encode('utf-8')
            f.write(data)

    def add_instance_metadata(self, instance_md):
        for (path, data) in instance_md.metadata_for_config_drive():
            self.mdfiles.append((path, data))

    def _write_md_files(self, basedir):
        for data in self.mdfiles:
            self._add_file(basedir, data[0], data[1])

    def _make_iso9660(self, path, tmpdir):
        publisher = "%(product)s %(version)s" % {
            'product': version.product_string(),
            'version': version.version_string_with_package()
            }

        processutils.execute(CONF.mkisofs_cmd,
                             '-o', path,
                             '-ldots',
                             '-allow-lowercase',
                             '-allow-multidot',
                             '-l',
                             '-publisher',
                             publisher,
                             '-quiet',
                             '-J',
                             '-r',
                             '-V', 'config-2',
                             tmpdir,
                             attempts=1,
                             run_as_root=False)

    def _make_vfat(self, path, tmpdir):
        # NOTE(mikal): This is a little horrible, but I couldn't find an
        # equivalent to genisoimage for vfat filesystems.
        with open(path, 'wb') as f:
            f.truncate(CONFIGDRIVESIZE_BYTES)

        nova.privsep.fs.unprivileged_mkfs('vfat', path, label='config-2')

        with utils.tempdir() as mountdir:
            mounted = False
            try:
                _, err = nova.privsep.fs.mount(
                    None, path, mountdir,
                    ['-o', 'loop,uid=%d,gid=%d' % (os.getuid(), os.getgid())])
                if err:
                    raise exception.ConfigDriveMountFailed(operation='mount',
                                                           error=err)
                mounted = True

                # NOTE(mikal): I can't just use shutils.copytree here,
                # because the destination directory already
                # exists. This is annoying.
                for ent in os.listdir(tmpdir):
                    shutil.copytree(os.path.join(tmpdir, ent),
                                    os.path.join(mountdir, ent))

            finally:
                if mounted:
                    nova.privsep.fs.umount(mountdir)

    def make_drive(self, path):
        """Make the config drive.

        :param path: the path to place the config drive image at

        :raises ProcessExecuteError if a helper process has failed.
        """
        with utils.tempdir() as tmpdir:
            self._write_md_files(tmpdir)

            if CONF.config_drive_format == 'iso9660':
                self._make_iso9660(path, tmpdir)
            elif CONF.config_drive_format == 'vfat':
                self._make_vfat(path, tmpdir)
            else:
                raise exception.ConfigDriveUnknownFormat(
                    format=CONF.config_drive_format)

    def cleanup(self):
        if self.imagefile:
            fileutils.delete_if_exists(self.imagefile)

    def __repr__(self):
        return "<ConfigDriveBuilder: " + str(self.mdfiles) + ">"


def required_by(instance):

    image_prop = instance.image_meta.properties.get(
        "img_config_drive",
        fields.ConfigDrivePolicy.OPTIONAL)

    return (instance.config_drive or
            CONF.force_config_drive or
            image_prop == fields.ConfigDrivePolicy.MANDATORY
            )


def update_instance(instance):
    """Update the instance config_drive setting if necessary

    The image or configuration file settings may override the default instance
    setting. In this case the instance needs to mirror the actual
    virtual machine configuration.
    """
    if not instance.config_drive and required_by(instance):
        instance.config_drive = True
