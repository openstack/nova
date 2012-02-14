# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2011 OpenStack LLC.
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

from nova.api.openstack import extensions as base_extensions
from nova import flags
from nova import log as logging


LOG = logging.getLogger(__name__)
FLAGS = flags.FLAGS


class ExtensionManager(base_extensions.ExtensionManager):
    def __init__(self):
        LOG.audit(_('Initializing extension manager.'))

        self.cls_list = FLAGS.osapi_volume_extension
        self.extensions = {}
        self._load_extensions()
