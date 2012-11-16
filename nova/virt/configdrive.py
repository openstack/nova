# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

from nova import config
from nova import exception
from nova.openstack.common import cfg
from nova.openstack.common import fileutils
from nova.openstack.common import log as logging
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
               default=None,
               help='Set to force injection to take place on a config drive '
                    '(if set, valid options are: always)'),
    cfg.StrOpt('mkisofs_cmd',
               default='genisoimage',
               help='Name and optionally path of the tool used for '
                    'ISO image creation')
    ]

CONF = config.CONF
CONF.register_opts(configdrive_opts)


class ConfigDriveBuilder(object):
    def __init__(self, instance_md=None):
        self.imagefile = None

        # TODO(mikal): I don't think I can use utils.tempdir here, because
        # I need to have the directory last longer than the scope of this
        # method call
        self.tempdir = tempfile.mkdtemp(dir=CONF.config_drive_tempdir,
                                        prefix='cd_gen_')

        if instance_md is not None:
            self.add_instance_metadata(instance_md)

    def _add_file(self, path, data):
        filepath = os.path.join(self.tempdir, path)
        dirname = os.path.dirname(filepath)
        fileutils.ensure_tree(dirname)
        with open(filepath, 'w') as f:
            f.write(data)

    def add_instance_metadata(self, instance_md):
        for (path, value) in instance_md.metadata_for_config_drive():
            self._add_file(path, value)
            LOG.debug(_('Added %(filepath)s to config drive'),
                      {'filepath': path})

    def _make_iso9660(self, path):
        utils.execute(CONF.mkisofs_cmd,
                      '-o', path,
                      '-ldots',
                      '-allow-lowercase',
                      '-allow-multidot',
                      '-l',
                      '-publisher', ('"OpenStack nova %s"'
                                     % version.version_string()),
                      '-quiet',
                      '-J',
                      '-r',
                      '-V', 'config-2',
                      self.tempdir,
                      attempts=1,
                      run_as_root=False)

    def _make_vfat(self, path):
        # NOTE(mikal): This is a little horrible, but I couldn't find an
        # equivalent to genisoimage for vfat filesystems. vfat images are
        # always 64mb.
        with open(path, 'w') as f:
            f.truncate(64 * 1024 * 1024)

        utils.mkfs('vfat', path, label='config-2')

        mounted = False
        try:
            mountdir = tempfile.mkdtemp(dir=CONF.config_drive_tempdir,
                                        prefix='cd_mnt_')
            _out, err = utils.trycmd('mount', '-o', 'loop', path, mountdir,
                                     run_as_root=True)
            if err:
                raise exception.ConfigDriveMountFailed(operation='mount',
                                                       error=err)
            mounted = True

            _out, err = utils.trycmd('chown',
                                     '%s.%s' % (os.getuid(), os.getgid()),
                                     mountdir, run_as_root=True)
            if err:
                raise exception.ConfigDriveMountFailed(operation='chown',
                                                       error=err)

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
        if CONF.config_drive_format == 'iso9660':
            self._make_iso9660(path)
        elif CONF.config_drive_format == 'vfat':
            self._make_vfat(path)
        else:
            raise exception.ConfigDriveUnknownFormat(
                format=CONF.config_drive_format)

    def cleanup(self):
        if self.imagefile:
            utils.delete_if_exists(self.imagefile)

        try:
            shutil.rmtree(self.tempdir)
        except OSError, e:
            LOG.error(_('Could not remove tmpdir: %s'), str(e))


def required_by(instance):
    return instance.get('config_drive') or CONF.force_config_drive


def enabled_for(instance):
    return required_by(instance) or instance.get('config_drive_id')
