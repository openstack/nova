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


image_file_url_group = cfg.OptGroup(
    'image_file_url',
    title='Image File URL Options')

filesystems = cfg.ListOpt(
    name='filesystems',
    default=[],
    deprecated_for_removal=True,
    deprecated_since="14.0.0",
    deprecated_reason="""
The feature to download images from glance via filesystem is not used and will
be removed in the future.
""",
    help="""
List of file systems that are configured in this file in the
image_file_url:<list entry name> sections
""")

# NOTE(jbresnah) because the group under which these options are added is
# dynamically determined these options need to stay out of global space
# or they will confuse generate_sample.sh
filesystem_opts = [
     cfg.StrOpt('id',
                deprecated_for_removal=True,
                deprecated_since="14.0.0",
                deprecated_reason="""
The feature to download images from glance via filesystem is not used and will
be removed in the future.
""",
                help="""
A unique ID given to each file system.  This is value is set in Glance and
agreed upon here so that the operator knowns they are dealing with the same
file system.
"""),
     cfg.StrOpt('mountpoint',
                deprecated_for_removal=True,
                deprecated_since="14.0.0",
                deprecated_reason="""
The feature to download images from glance via filesystem is not used and will
be removed in the future.
""",
                help="""
The path at which the file system is mounted.
"""),
]

ALL_OPTS = [filesystems]


def register_opts(conf):
    conf.register_group(image_file_url_group)
    conf.register_opts(ALL_OPTS, group=image_file_url_group)
    for fs in conf.image_file_url.filesystems:
        group_name = 'image_file_url:' + fs
        conf.register_opts(filesystem_opts, group=group_name)


def list_opts():
    # NOTE(markus_z): As the "filesystem" opt has an empty list as a default
    # value and this value is necessary for a correct group name, we cannot
    # list the "filesystem_opts" for the "nova.conf.sample" file here. A
    # follow up patch will deprecate those. Due to their dynamic creation
    # they never got shown in "nova.conf.sample" nor the config reference
    # manual. I see no need to change this here with a dummy group or something
    # like that.
    return {image_file_url_group: ALL_OPTS}
