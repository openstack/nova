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
"""WSGI script for Placement API

WSGI handler for running Placement API under Apache2, nginx, gunicorn etc.
"""

import logging as py_logging
import os
import os.path

from oslo_log import log as logging
from oslo_middleware import cors
from oslo_policy import opts as policy_opts
from oslo_utils import importutils
import pbr.version

from nova.api.openstack.placement import db_api
from nova.api.openstack.placement import deploy
from nova import conf


profiler = importutils.try_import('osprofiler.opts')


CONFIG_FILE = 'nova.conf'


version_info = pbr.version.VersionInfo('nova')


def setup_logging(config):
    # Any dependent libraries that have unhelp debug levels should be
    # pinned to a higher default.
    extra_log_level_defaults = [
        'routes=INFO',
    ]
    logging.set_defaults(default_log_levels=logging.get_default_log_levels() +
                    extra_log_level_defaults)
    logging.setup(config, 'nova')
    py_logging.captureWarnings(True)


def _get_config_file(env=None):
    if env is None:
        env = os.environ

    dirname = env.get('OS_PLACEMENT_CONFIG_DIR', '/etc/nova').strip()
    return os.path.join(dirname, CONFIG_FILE)


def _parse_args(argv, default_config_files):
    logging.register_options(conf.CONF)

    if profiler:
        profiler.set_defaults(conf.CONF)

    _set_middleware_defaults()

    # This is needed so we can check [oslo_policy]/enforce_scope in the
    # deploy module.
    policy_opts.set_defaults(conf.CONF)

    conf.CONF(argv[1:], project='nova', version=version_info.version_string(),
              default_config_files=default_config_files)


def _set_middleware_defaults():
    """Update default configuration options for oslo.middleware."""
    cors.set_defaults(
        allow_headers=['X-Auth-Token',
                       'X-Openstack-Request-Id',
                       'X-Identity-Status',
                       'X-Roles',
                       'X-Service-Catalog',
                       'X-User-Id',
                       'X-Tenant-Id'],
        expose_headers=['X-Auth-Token',
                        'X-Openstack-Request-Id',
                        'X-Subject-Token',
                        'X-Service-Token'],
        allow_methods=['GET',
                       'PUT',
                       'POST',
                       'DELETE',
                       'PATCH']
    )


def init_application():
    # initialize the config system
    conffile = _get_config_file()

    # NOTE(lyarwood): Call reset to ensure the ConfigOpts object doesn't
    # already contain registered options if the app is reloaded.
    conf.CONF.reset()

    _parse_args([], default_config_files=[conffile])
    db_api.configure(conf.CONF)

    # initialize the logging system
    setup_logging(conf.CONF)

    # dump conf at debug if log_options
    if conf.CONF.log_options:
        conf.CONF.log_opt_values(
            logging.getLogger(__name__),
            logging.DEBUG)

    # build and return our WSGI app
    return deploy.loadapp(conf.CONF)
