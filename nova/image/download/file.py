# Copyright 2013 Red Hat, Inc.
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

import logging

from oslo.config import cfg

from nova import exception
from nova.i18n import _, _LI
import nova.image.download.base as xfer_base
import nova.virt.libvirt.utils as lv_utils


CONF = cfg.CONF
LOG = logging.getLogger(__name__)

opt_group = cfg.ListOpt(name='filesystems', default=[],
                        help=_('List of file systems that are configured '
                               'in this file in the '
                               'image_file_url:<list entry name> '
                               'sections'))
CONF.register_opt(opt_group, group="image_file_url")


#  This module extends the configuration options for nova.conf.  If the user
#  wishes to use the specific configuration settings the following needs to
#  be added to nova.conf:
#  [image_file_url]
#  filesystem = <a list of strings referencing a config section>
#
#  For each entry in the filesystem list a new configuration section must be
#  added with the following format:
#  [image_file_url:<list entry>]
#  id = <string>
#  mountpoint = <string>
#
#    id:
#        An opaque string.  In order for this module to know that the remote
#        FS is the same one that is mounted locally it must share information
#        with the glance deployment.  Both glance and nova-compute must be
#        configured with a unique matching string.  This ensures that the
#        file:// advertised URL is describing a file system that is known
#        to nova-compute
#    mountpoint:
#        The location at which the file system is locally mounted.  Glance
#        may mount a shared file system on a different path than nova-compute.
#        This value will be compared against the metadata advertised with
#        glance and paths will be adjusted to ensure that the correct file
#        file is copied.
#
#  If these values are not added to nova.conf and the file module is in the
#  allowed_direct_url_schemes list, then the legacy behavior will occur such
#  that a copy will be attempted assuming that the glance and nova file systems
#  are the same.


class FileTransfer(xfer_base.TransferBase):

    desc_required_keys = ['id', 'mountpoint']

    # NOTE(jbresnah) because the group under which these options are added is
    # dyncamically determined these options need to stay out of global space
    # or they will confuse generate_sample.sh
    filesystem_opts = [
         cfg.StrOpt('id',
                    help=_('A unique ID given to each file system.  This is '
                           'value is set in Glance and agreed upon here so '
                           'that the operator knowns they are dealing with '
                           'the same file system.')),
         cfg.StrOpt('mountpoint',
                    help=_('The path at which the file system is mounted.')),
    ]

    def _get_options(self):
        fs_dict = {}
        for fs in CONF.image_file_url.filesystems:
            group_name = 'image_file_url:' + fs
            conf_group = CONF[group_name]
            if conf_group.id is None:
                msg = _('The group %s(group_name) must be configured with '
                        'an id.')
                raise exception.ImageDownloadModuleConfigurationError(
                    module=str(self), reason=msg)
            fs_dict[CONF[group_name].id] = CONF[group_name]
        return fs_dict

    def __init__(self):
        # create the needed options
        for fs in CONF.image_file_url.filesystems:
            group_name = 'image_file_url:' + fs
            CONF.register_opts(self.filesystem_opts, group=group_name)

    def _verify_config(self):
        for fs_key in self.filesystems:
            for r in self.desc_required_keys:
                fs_ent = self.filesystems[fs_key]
                if fs_ent[r] is None:
                    msg = _('The key %s is required in all file system '
                            'descriptions.')
                    LOG.error(msg)
                    raise exception.ImageDownloadModuleConfigurationError(
                        module=str(self), reason=msg)

    def _file_system_lookup(self, metadata, url_parts):
        for r in self.desc_required_keys:
            if r not in metadata:
                url = url_parts.geturl()
                msg = _('The key %(r)s is required in the location metadata '
                        'to access the url %(url)s.') % {'r': r, 'url': url}
                LOG.info(msg)
                raise exception.ImageDownloadModuleMetaDataError(
                    module=str(self), reason=msg)
        id = metadata['id']
        if id not in self.filesystems:
            msg = _('The ID %(id)s is unknown.') % {'id': id}
            LOG.info(msg)
            return
        fs_descriptor = self.filesystems[id]
        return fs_descriptor

    def _normalize_destination(self, nova_mount, glance_mount, path):
        if not path.startswith(glance_mount):
            msg = (_('The mount point advertised by glance: %(glance_mount)s, '
                     'does not match the URL path: %(path)s') %
                     {'glance_mount': glance_mount, 'path': path})
            raise exception.ImageDownloadModuleMetaDataError(
                module=str(self), reason=msg)
        new_path = path.replace(glance_mount, nova_mount, 1)
        return new_path

    def download(self, context, url_parts, dst_file, metadata, **kwargs):
        self.filesystems = self._get_options()
        if not self.filesystems:
            # NOTE(jbresnah) when nothing is configured assume legacy behavior
            nova_mountpoint = '/'
            glance_mountpoint = '/'
        else:
            self._verify_config()
            fs_descriptor = self._file_system_lookup(metadata, url_parts)
            if fs_descriptor is None:
                msg = (_('No matching ID for the URL %s was found.') %
                        url_parts.geturl())
                raise exception.ImageDownloadModuleError(reason=msg,
                                                    module=str(self))
            nova_mountpoint = fs_descriptor['mountpoint']
            glance_mountpoint = metadata['mountpoint']

        source_file = self._normalize_destination(nova_mountpoint,
                                                  glance_mountpoint,
                                                  url_parts.path)
        lv_utils.copy_image(source_file, dst_file)
        LOG.info(_LI('Copied %(source_file)s using %(module_str)s'),
                 {'source_file': source_file, 'module_str': str(self)})


def get_download_handler(**kwargs):
    return FileTransfer()


def get_schemes():
    return ['file', 'filesystem']
