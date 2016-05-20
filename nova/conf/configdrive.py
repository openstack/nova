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

config_drive_format_opt = cfg.StrOpt('config_drive_format',
        default='iso9660',
        choices=('iso9660', 'vfat'),
        help="""
Configuration drive format
""")

force_config_drive_opt = cfg.BoolOpt('force_config_drive',
        default=False,
        help="""
Force injection to take place on a config drive
""")

mkisofs_cmd_opt = cfg.StrOpt('mkisofs_cmd',
        default='genisoimage',
        help="""
Name and optionally path of the tool used for ISO image creation
""")

ALL_OPTS = [config_drive_format_opt,
            force_config_drive_opt,
            mkisofs_cmd_opt]


def register_opts(conf):
    conf.register_opts(ALL_OPTS)


def list_opts():
    return {"DEFAULT": ALL_OPTS}
