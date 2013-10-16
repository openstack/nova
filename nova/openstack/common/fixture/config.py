# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2013 Mirantis, Inc.
# Copyright 2013 OpenStack Foundation
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
import fixtures
from oslo.config import cfg
import six


class Config(fixtures.Fixture):
    """Override some configuration values.

    The keyword arguments are the names of configuration options to
    override and their values.

    If a group argument is supplied, the overrides are applied to
    the specified configuration option group.

    All overrides are automatically cleared at the end of the current
    test by the reset() method, which is registred by addCleanup().
    """

    def __init__(self, conf=cfg.CONF):
        self.conf = conf

    def setUp(self):
        super(Config, self).setUp()
        self.addCleanup(self.conf.reset)

    def config(self, **kw):
        group = kw.pop('group', None)
        for k, v in six.iteritems(kw):
            self.conf.set_override(k, v, group)
