# Copyright 2013 Red Hat, Inc.
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

"""Provides OpenStack config generators

This module defines a class for configuration
generators for generating the model in
:mod:`openstack.common.report.models.conf`.
"""

from oslo.config import cfg

from nova.openstack.common.report.models import conf as cm


class ConfigReportGenerator(object):
    """A Configuration Data Generator

    This generator returns
    :class:`openstack.common.report.models.conf.ConfigModel`,
    by default using the configuration options stored
    in :attr:`oslo.config.cfg.CONF`, which is where
    OpenStack stores everything.

    :param cnf: the configuration option object
    :type cnf: :class:`oslo.config.cfg.ConfigOpts`
    """

    def __init__(self, cnf=cfg.CONF):
        self.conf_obj = cnf

    def __call__(self):
        return cm.ConfigModel(self.conf_obj)
