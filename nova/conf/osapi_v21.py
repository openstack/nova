# Copyright 2015 OpenStack Foundation
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


api_opts = [
        cfg.ListOpt('extensions_blacklist',
                    default=[],
                    help='DEPRECATED: A list of v2.1 API extensions to never '
                    'load. Specify the extension aliases here. '
                    'This option will be removed in the near future. '
                    'After that point you have to run all of the API.',
                    deprecated_for_removal=True, deprecated_group='osapi_v21'),
        cfg.ListOpt('extensions_whitelist',
                    default=[],
                    help='DEPRECATED: If the list is not empty then a v2.1 '
                    'API extension will only be loaded if it exists in this '
                    'list. Specify the extension aliases here. '
                    'This option will be removed in the near future. '
                    'After that point you have to run all of the API.',
                    deprecated_for_removal=True, deprecated_group='osapi_v21'),
        cfg.StrOpt('project_id_regex',
                   default=None,
                   help='DEPRECATED: The validation regex for project_ids '
                   'used in urls. This defaults to [0-9a-f\-]+ if not set, '
                   'which matches normal uuids created by keystone.',
                   deprecated_for_removal=True, deprecated_group='osapi_v21')
]

api_opts_group = cfg.OptGroup(name="osapi_v21", title="API v2.1 Options")


def register_opts(conf):
    conf.register_group(api_opts_group)
    conf.register_opts(api_opts, api_opts_group)


def list_opts():
    return {api_opts_group: api_opts}
