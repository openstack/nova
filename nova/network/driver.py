# Copyright 2012 Red Hat, Inc.
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

import sys

from oslo_log import log as logging
from oslo_utils import importutils

import nova.conf
from nova.i18n import _LE, _LI


CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)


def load_network_driver(network_driver=None):
    if not network_driver:
        network_driver = CONF.network_driver

    if not network_driver:
        LOG.error(_LE("Network driver option required, but not specified"))
        sys.exit(1)

    LOG.info(_LI("Loading network driver '%s'"), network_driver)

    return importutils.import_module(network_driver)
