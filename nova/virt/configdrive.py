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
import tempfile

from oslo.config import cfg

from nova import exception
from nova.openstack.common import fileutils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import units
from nova import utils
from nova import version

LOG = logging.getLogger(__name__)

configdrive_opts = [
    cfg.StrOpt('config_drive_format',
               default='iso9660',
               help='Config drive format. One of iso9660 (default) or vfat'),
    cfg.StrOpt('config_drive_tempdir',
               default=tempfile.tempdir,
               help=('Where to put temporary files associated with '
                     'config drive creation')),
    # force_config_drive is a string option, to allow for future behaviors
    #  (e.g. use config_drive based on image properties)
    cfg.StrOpt('force_config_drive',
               help='Set to force injection to take place on a config drive '
                    '(if set, valid options are: always)'),
    cfg.StrOpt('mkisofs_cmd',
               default='genisoimage',
               help='Name and optionally path of the tool used for '
                    'ISO image creation')
    ]

CONF = cfg.CONF
CONF.register_opts(configdrive_opts)

# Config drives are 64mb, if we can't size to the exact size of the data
CONFIGDRIVESIZE_BYTES = 64 * units.Mi


class ConfigDriveBuilder(object):
    """Build config drives, optionally as a context manager."""

    def __init__(self, instance_md=None):
        self.imagefile = None

        # TODO(mikal): I don't think I can use utils.tempdir here, because
        # I need to have the directory last longer than the scope of this
        # method call
        self.tempdir = tempfile.mkdtemp(dir=CONF.config_drive_tempdir,
                                        prefix='cd_gen_')

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

    def _add_file(self, path, data):
        filepath = os.path.join(self.tempdir, path)
        dirname = os.path.dirname(filepath)
        fileutils.ensure_tree(dirname)
        with open(filepath, 'wb') as f:
            f.write(data)

    def add_instance_metadata(self, instance_md):
        for (path, value) in instance_md.metadata_for_config_drive():
            self._add_file(path, value)
            LOG.debug('Added %(filepath)s to config drive',
                      {'filepath': path})

    def _make_iso9660(self, path):
        publisher = "%(product)s %(version)s" % {
            'product': version.product_string(),
            'version': version.version_string_with_package()
            }

        utils.execute(CONF.mkisofs_cmd,
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
                      self.tempdir,
                      attempts=1,
                      run_as_root=False)

    def _make_vfat(self, path):
        # NOTE(mikal): This is a little horrible, but I couldn't find an
        # equivalent to genisoimage for vfat filesystems.
        with open(path, 'wb') as f:
            f.truncate(CONFIGDRIVESIZE_BYTES)

        utils.mkfs('vfat', path, label='config-2')

        mounted = False
        try:
            mountdir = tempfile.mkdtemp(dir=CONF.config_drive_tempdir,
                                        prefix='cd_mnt_')
            _out, err = utils.trycmd('mount', '-o',
                                     'loop,uid=%d,gid=%d' % (os.getuid(),
                                                             os.getgid()),
                                     path, mountdir,
                                     run_as_root=True)
            if err:
                raise exception.ConfigDriveMountFailed(operation='mount',
                                                       error=err)
            mounted = True

            # NOTE(mikal): I can't just use shutils.copytree here, because the
            # destination directory already exists. This is annoying.
            for ent in os.listdir(self.tempdir):
                shutil.copytree(os.path.join(self.tempdir, ent),
                                os.path.join(mountdir, ent))

        finally:
            if mounted:
                utils.execute('umount', mountdir, run_as_root=True)
            shutil.rmtree(mountdir)

    def make_drive(self, path):
        """Make the config drive.

        :param path: the path to place the config drive image at

        :raises ProcessExecuteError if a helper process has failed.
        """
        if CONF.config_drive_format == 'iso9660':
            self._make_iso9660(path)
        elif CONF.config_drive_format == 'vfat':
            self._make_vfat(path)
        else:
            raise exception.ConfigDriveUnknownFormat(
                format=CONF.config_drive_format)

    def cleanup(self):
        if self.imagefile:
            fileutils.delete_if_exists(self.imagefile)

        try:
            shutil.rmtree(self.tempdir)
        except OSError as e:
            LOG.error(_('Could not remove tmpdir: %s'), str(e))


def required_by(instance):
    return instance.get('config_drive') or CONF.force_config_drive
