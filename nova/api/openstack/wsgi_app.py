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
"""WSGI application initialization for Nova APIs."""

import os

from oslo_config import cfg
from oslo_log import log as logging
from paste import deploy

from nova import config
from nova import context
from nova import exception
from nova import objects
from nova import service
from nova import utils

CONF = cfg.CONF

CONFIG_FILES = ['api-paste.ini', 'nova.conf']

utils.monkey_patch()
objects.register_all()


def _get_config_files(env=None):
    if env is None:
        env = os.environ
    dirname = env.get('OS_NOVA_CONFIG_DIR', '/etc/nova').strip()
    return [os.path.join(dirname, config_file)
            for config_file in CONFIG_FILES]


def _setup_service(host, name):
    binary = name if name.startswith('nova-') else "nova-%s" % name

    ctxt = context.get_admin_context()
    service_ref = objects.Service.get_by_host_and_binary(
        ctxt, host, binary)
    if service_ref:
        service._update_service_ref(service_ref)
    else:
        try:
            service_obj = objects.Service(ctxt)
            service_obj.host = host
            service_obj.binary = binary
            service_obj.topic = None
            service_obj.report_count = 0
            service_obj.create()
        except (exception.ServiceTopicExists,
                exception.ServiceBinaryExists):
            # If we race to create a record with a sibling, don't
            # fail here.
            pass


def error_application(exc, name):
    # TODO(cdent): make this something other than a stub
    def application(environ, start_response):
        start_response('500 Internal Server Error', [
            ('Content-Type', 'text/plain; charset=UTF-8')])
        return ['Out of date %s service %s\n' % (name, exc)]
    return application


def init_application(name):
    conf_files = _get_config_files()
    config.parse_args([], default_config_files=conf_files)

    logging.setup(CONF, "nova")
    try:
        _setup_service(CONF.host, name)
    except exception.ServiceTooOld as exc:
        return error_application(exc, name)

    conf = conf_files[0]

    return deploy.loadapp('config:%s' % conf, name=name)
