# Copyright (c) 2012 Rackspace Hosting
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

"""Starter script for Nova Cells Service."""

import sys

from oslo_log import log as logging
from oslo_reports import guru_meditation_report as gmr
from oslo_reports import opts as gmr_opts

from nova import cells
import nova.conf
from nova import config
from nova import objects
from nova import service
from nova import utils
from nova import version

CONF = nova.conf.CONF
LOG = logging.getLogger('nova.cells')


def main():
    config.parse_args(sys.argv)
    logging.setup(CONF, 'nova')
    utils.monkey_patch()
    objects.register_all()
    gmr_opts.set_defaults(CONF)

    gmr.TextGuruMeditation.setup_autorun(version, conf=CONF)

    LOG.warning('Cells v1 is deprecated in favor of Cells v2 and will be '
                'removed in the future.')
    server = service.Service.create(binary='nova-cells',
                                    topic=cells.TOPIC,
                                    manager='nova.cells.manager.CellsManager')
    service.serve(server)
    service.wait()
