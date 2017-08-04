# Copyright 2017 OpenStack Foundation
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
"""Common utilities for conf providers.

This module does not provide any actual conf options.
"""
from keystoneauth1 import loading as ks_loading
from oslo_config import cfg


_ADAPTER_VERSION_OPTS = ('version', 'min_version', 'max_version')


def get_ksa_adapter_opts(default_service_type, deprecated_opts=None):
    """Get auth, Session, and Adapter conf options from keystonauth1.loading.

    :param default_service_type: Default for the service_type conf option on
                                 the Adapter.
    :param deprecated_opts: dict of deprecated opts to register with the ksa
                            Adapter opts.  Works the same as the
                            deprecated_opts kwarg to:
                    keystoneauth1.loading.session.Session.register_conf_options
    :return: List of cfg.Opts.
    """
    opts = ks_loading.get_adapter_conf_options(include_deprecated=False,
                                               deprecated_opts=deprecated_opts)

    for opt in opts[:]:
        # Remove version-related opts.  Required/supported versions are
        # something the code knows about, not the operator.
        if opt.dest in _ADAPTER_VERSION_OPTS:
            opts.remove(opt)

    # Override defaults that make sense for nova
    cfg.set_defaults(opts,
                     valid_interfaces=['internal', 'public'],
                     service_type=default_service_type)
    return opts


def _dummy_opt(name):
    # A config option that can't be set by the user, so it behaves as if it's
    # ignored; but consuming code may expect it to be present in a conf group.
    return cfg.Opt(name, type=lambda x: None)


def register_ksa_opts(conf, group, default_service_type, include_auth=True,
                      deprecated_opts=None):
    """Register keystoneauth auth, Session, and Adapter opts.

    :param conf: oslo_config.cfg.CONF in which to register the options
    :param group: Conf group, or string name thereof, in which to register the
                  options.
    :param default_service_type: Default for the service_type conf option on
                                 the Adapter.
    :param include_auth: For service types where Nova is acting on behalf of
                         the user, auth should come from the user context.
                         In those cases, set this arg to False to avoid
                         registering ksa auth options.
    :param deprecated_opts: dict of deprecated opts to register with the ksa
                            Session or Adapter opts.  See docstring for
                            the deprecated_opts param of:
                    keystoneauth1.loading.session.Session.register_conf_options
    """
    # ksa register methods need the group name as a string.  oslo doesn't care.
    group = getattr(group, 'name', group)
    ks_loading.register_session_conf_options(
        conf, group, deprecated_opts=deprecated_opts)
    if include_auth:
        ks_loading.register_auth_conf_options(conf, group)
    conf.register_opts(get_ksa_adapter_opts(
        default_service_type, deprecated_opts=deprecated_opts), group=group)
    # Have to register dummies for the version-related opts we removed
    for name in _ADAPTER_VERSION_OPTS:
        conf.register_opt(_dummy_opt(name), group=group)


# NOTE(efried): Required for docs build.
def list_opts():
    return {}
