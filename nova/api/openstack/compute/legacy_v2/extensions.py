# Copyright 2011 OpenStack Foundation
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
from oslo_log import log as logging

from nova.api.openstack import extensions as base_extensions
from nova.i18n import _LW

STANDARD_EXTENSIONS = ('nova.api.openstack.compute.legacy_v2.contrib.' +
                       'standard_extensions')

ext_opts = [
    cfg.MultiStrOpt(
        'osapi_compute_extension',
        default=[STANDARD_EXTENSIONS],
        help='osapi compute extension to load. '
        'This option will be removed in the near future. '
        'After that point you have to run all of the API.',
        deprecated_for_removal=True),
]
CONF = cfg.CONF
CONF.register_opts(ext_opts)

LOG = logging.getLogger(__name__)


class ExtensionManager(base_extensions.ExtensionManager):
    def __init__(self):
        self.cls_list = CONF.osapi_compute_extension
        if (len(self.cls_list) > 0 and
                self.cls_list[0] != STANDARD_EXTENSIONS):
            LOG.warning(_LW('The extension configure options are deprecated. '
                            'In the near future you must run all of the API.'))
        self.extensions = {}
        self.sorted_ext_list = []
        self._load_extensions()
