# Copyright 2011 OpenStack Foundation
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License");
#    you may not use this file except in compliance with the License.
#    You may obtain a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS,
#    WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#    See the License for the specific language governing permissions and
#    limitations under the License.

"""Starter script for all nova services.

This script attempts to start all the nova services in one process.  Each
service is started in its own greenthread.  Please note that exceptions and
sys.exit() on the starting of a service are logged and the script will
continue attempting to launch the rest of the services.

"""

import sys

from oslo_config import cfg

from nova import config
from nova.i18n import _LE
from nova import objects
from nova.objectstore import s3server
from nova.openstack.common import log as logging
from nova import service
from nova import utils
from nova.vnc import xvp_proxy


CONF = cfg.CONF
CONF.import_opt('manager', 'nova.conductor.api', group='conductor')
CONF.import_opt('topic', 'nova.conductor.api', group='conductor')
CONF.import_opt('enabled_apis', 'nova.service')
CONF.import_opt('enabled_ssl_apis', 'nova.service')


def main():
    config.parse_args(sys.argv)
    logging.setup("nova")
    LOG = logging.getLogger('nova.all')
    utils.monkey_patch()
    objects.register_all()
    launcher = service.process_launcher()

    # nova-api
    for api in CONF.enabled_apis:
        try:
            should_use_ssl = api in CONF.enabled_ssl_apis
            server = service.WSGIService(api, use_ssl=should_use_ssl)
            launcher.launch_service(server, workers=server.workers or 1)
        except (Exception, SystemExit):
            LOG.exception(_LE('Failed to load %s-api'), api)

    for mod in [s3server, xvp_proxy]:
        try:
            launcher.launch_service(mod.get_wsgi_server())
        except (Exception, SystemExit):
            LOG.exception(_LE('Failed to load %s'), mod.__name__)

    for binary in ['nova-compute', 'nova-network', 'nova-scheduler',
                   'nova-cert', 'nova-conductor']:

        # FIXME(sirp): Most service configs are defined in nova/service.py, but
        # conductor has set a new precedent of storing these configs
        # nova/<service>/api.py.
        #
        # We should update the existing services to use this new approach so we
        # don't have to treat conductor differently here.
        if binary == 'nova-conductor':
            topic = CONF.conductor.topic
            manager = CONF.conductor.manager
        else:
            topic = None
            manager = None

        try:
            launcher.launch_service(service.Service.create(binary=binary,
                                                           topic=topic,
                                                          manager=manager))
        except (Exception, SystemExit):
            LOG.exception(_LE('Failed to load %s'), binary)
    launcher.wait()
