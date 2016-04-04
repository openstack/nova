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

from oslo_config import cfg

from nova.i18n import _

image_file_url_group = cfg.OptGroup(
    'image_file_url',
    title='Image File URL Options')

filesystems = cfg.ListOpt(
    name='filesystems',
    default=[],
    help=_('List of file systems that are configured '
           'in this file in the '
           'image_file_url:<list entry name> '
           'sections'))

ALL_OPTS = [filesystems]


def register_opts(conf):
    conf.register_group(image_file_url_group)
    conf.register_opts(ALL_OPTS, group=image_file_url_group)


def list_opts():
    return {image_file_url_group: ALL_OPTS}
