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

STANDARD_EXTENSIONS = ('nova.api.openstack.compute.legacy_v2.contrib.' +
                       'standard_extensions')

osapi_ext_list_opt = cfg.ListOpt('osapi_compute_ext_list',
        default=[],
        help='DEPRECATED: Specify list of extensions to load when '
             'using osapi_compute_extension option with nova.api.'
             'openstack.compute.legacy_v2.contrib.select_extensions '
             'This option will be removed in the near future. '
             'After that point you have to run all of the API.',
        deprecated_for_removal=True)

osapi_comp_ext_opt = cfg.MultiStrOpt(
        'osapi_compute_extension',
        default=[STANDARD_EXTENSIONS],
        help='The osapi compute extension to load. '
             'This option will be removed in the near future. '
             'After that point you have to run all of the API.',
        deprecated_for_removal=True)

ALL_OPTS = [osapi_ext_list_opt] + [osapi_comp_ext_opt]


def register_opts(conf):
    conf.register_opt(osapi_ext_list_opt)
    conf.register_opt(osapi_comp_ext_opt)


def list_opts():
    return {"DEFAULT": ALL_OPTS}
