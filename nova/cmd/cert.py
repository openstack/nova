# Copyright 2012 OpenStack Foundation
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

"""Starter script for Nova Cert."""

import sys

from oslo_log import log as logging
from oslo_log import versionutils
from oslo_reports import guru_meditation_report as gmr

import nova.conf
from nova import config
from nova.i18n import _LW
from nova import objects
from nova import service
from nova import utils
from nova import version

CONF = nova.conf.CONF


def main():
    config.parse_args(sys.argv)
    logging.setup(CONF, "nova")
    utils.monkey_patch()
    objects.register_all()
    log = logging.getLogger(__name__)
    versionutils.report_deprecated_feature(
        log,
        _LW('The nova-cert service is deprecated and will be removed '
            'in a future release.'))

    gmr.TextGuruMeditation.setup_autorun(version)

    server = service.Service.create(binary='nova-cert')
    service.serve(server)
    service.wait()
