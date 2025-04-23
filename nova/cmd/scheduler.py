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

"""Starter script for Nova Scheduler."""

import sys

from oslo_concurrency import processutils
from oslo_log import log as logging
from oslo_reports import guru_meditation_report as gmr
from oslo_reports import opts as gmr_opts

import nova.conf
from nova import config
from nova import objects
from nova.scheduler import rpcapi
from nova import service
from nova import utils
from nova import version

CONF = nova.conf.CONF


def main():
    config.parse_args(sys.argv)
    logging.setup(CONF, "nova")
    objects.register_all()
    gmr_opts.set_defaults(CONF)
    objects.Service.enable_min_version_cache()

    gmr.TextGuruMeditation.setup_autorun(version, conf=CONF)

    server = service.Service.create(
        binary='nova-scheduler', topic=rpcapi.RPC_TOPIC)

    # Determine the number of workers; if not specified in config, default
    # to number of CPUs
    workers = CONF.scheduler.workers or processutils.get_worker_count()
    # NOTE(gibi): The oslo.service backend creates the worker processes
    # via os.fork. As nova already initialized these executor(s)
    # in the master process, and os.fork's behavior is to copy the state of
    # parent to the child process, we destroy the executor in the parent
    # process before the forking, so that the workers initialize new
    # executor(s) and therefore avoid working with the wrong internal executor
    # state (i.e. number of workers idle in the pool). A long therm solution
    # would be to use os.spawn instead of os.fork for the workers.
    utils.destroy_scatter_gather_executor()

    service.serve(server, workers=workers)
    service.wait()
