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

import shlex
import sys

import os_vif
from oslo_log import log as logging
from oslo_privsep import priv_context
from oslo_reports import guru_meditation_report as gmr
from oslo_reports import opts as gmr_opts

from nova.cmd import common as cmd_common
from nova.compute import rpcapi as compute_rpcapi
from nova.conductor import rpcapi as conductor_rpcapi
import nova.conf
from nova.conf import remote_debug
from nova import config
from nova import objects
from nova.objects import base as objects_base
from nova import service
from nova import utils
from nova import version

CONF = nova.conf.CONF
remote_debug.register_cli_opts(CONF)


def main():
    config.parse_args(sys.argv)
    logging.setup(CONF, 'nova')
    priv_context.init(root_helper=shlex.split(utils.get_root_helper()))
    objects.register_all()
    gmr_opts.set_defaults(CONF)
    # Ensure os-vif objects are registered and plugins loaded
    os_vif.initialize()

    gmr.TextGuruMeditation.setup_autorun(version, conf=CONF)

    cmd_common.block_db_access('nova-compute')
    objects_base.NovaObject.indirection_api = conductor_rpcapi.ConductorAPI()
    objects.Service.enable_min_version_cache()
    server = service.Service.create(binary='nova-compute',
                                    topic=compute_rpcapi.RPC_TOPIC)
    service.serve(server)
    service.wait()
