# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Starter script for Nova Compute."""

import sys
import traceback

from oslo.config import cfg

from nova.conductor import rpcapi as conductor_rpcapi
from nova import config
import nova.db.api
from nova import exception
from nova.i18n import _LE
from nova import objects
from nova.objects import base as objects_base
from nova.openstack.common import log as logging
from nova.openstack.common.report import guru_meditation_report as gmr
from nova import service
from nova import utils
from nova import version

CONF = cfg.CONF
CONF.import_opt('compute_topic', 'nova.compute.rpcapi')
CONF.import_opt('use_local', 'nova.conductor.api', group='conductor')


def block_db_access():
    class NoDB(object):
        def __getattr__(self, attr):
            return self

        def __call__(self, *args, **kwargs):
            stacktrace = "".join(traceback.format_stack())
            LOG = logging.getLogger('nova.compute')
            LOG.error(_LE('No db access allowed in nova-compute: %s'),
                      stacktrace)
            raise exception.DBNotAllowed('nova-compute')

    nova.db.api.IMPL = NoDB()


def main():
    config.parse_args(sys.argv)
    logging.setup('nova')
    utils.monkey_patch()
    objects.register_all()

    gmr.TextGuruMeditation.setup_autorun(version)

    if not CONF.conductor.use_local:
        block_db_access()
        objects_base.NovaObject.indirection_api = \
            conductor_rpcapi.ConductorAPI()

    server = service.Service.create(binary='nova-compute',
                                    topic=CONF.compute_topic,
                                    db_allowed=CONF.conductor.use_local)
    service.serve(server)
    service.wait()
