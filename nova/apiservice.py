# vim: tabstop=4 shiftwidth=4 softtabstop=4

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

"""
Wrapper for API service, makes it look more like the non-WSGI services
"""

from nova import flags
from nova import log as logging
from nova import version
from nova import wsgi


LOG = logging.getLogger('nova.api')

FLAGS = flags.FLAGS
flags.DEFINE_string('ec2_listen', "0.0.0.0",
                    'IP address for EC2 API to listen')
flags.DEFINE_integer('ec2_listen_port', 8773, 'port for ec2 api to listen')
flags.DEFINE_string('osapi_listen', "0.0.0.0",
                    'IP address for OpenStack API to listen')
flags.DEFINE_integer('osapi_listen_port', 8774, 'port for os api to listen')

API_ENDPOINTS = ['ec2', 'osapi']


def _run_app(paste_config_file):
    LOG.debug(_("Using paste.deploy config at: %s"), paste_config_file)
    apps = []
    for api in API_ENDPOINTS:
        config = wsgi.load_paste_configuration(paste_config_file, api)
        if config is None:
            LOG.debug(_("No paste configuration for app: %s"), api)
            continue
        LOG.debug(_("App Config: %(api)s\n%(config)r") % locals())
        LOG.info(_("Running %s API"), api)
        app = wsgi.load_paste_app(paste_config_file, api)
        apps.append((app, getattr(FLAGS, "%s_listen_port" % api),
                     getattr(FLAGS, "%s_listen" % api)))
    if len(apps) == 0:
        LOG.error(_("No known API applications configured in %s."),
                  paste_config_file)
        return

    server = wsgi.Server()
    for app in apps:
        server.start(*app)
    return server


class ApiService(object):
    """Base class for workers that run on hosts."""

    def __init__(self, conf):
        self.conf = conf
        self.wsgi_app = None

    def start(self):
        self.wsgi_app = _run_app(self.conf)

    def wait(self):
        self.wsgi_app.wait()

    @staticmethod
    def create():
        conf = wsgi.paste_config_file('nova-api.conf')
        return serve(conf)


def serve(conf):
    LOG.audit(_("Starting nova-api node (version %s)"),
              version.version_string_with_vcs())
    LOG.debug(_("Full set of FLAGS:"))
    for flag in FLAGS:
        flag_get = FLAGS.get(flag, None)
        LOG.debug("%(flag)s : %(flag_get)s" % locals())

    service = ApiService(conf)
    service.start()

    return service
