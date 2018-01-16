# Copyright (c) 2014-2017 Red Hat, Inc
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_config import cfg

from nova.console.rfb import authnone
from nova.console.rfb import authvencrypt
from nova import exception

CONF = cfg.CONF


class RFBAuthSchemeList(object):

    AUTH_SCHEME_MAP = {
        "none": authnone.RFBAuthSchemeNone,
        "vencrypt": authvencrypt.RFBAuthSchemeVeNCrypt,
    }

    def __init__(self):
        self.schemes = {}

        for name in CONF.vnc.auth_schemes:
            scheme = self.AUTH_SCHEME_MAP[name]()

            self.schemes[scheme.security_type()] = scheme

    def find_scheme(self, desired_types):
        """Find a suitable authentication scheme to use with compute node.

        Identify which of the ``desired_types`` we can accept.

        :param desired_types: A list of ints corresponding to the various
            authentication types supported.
        """
        for security_type in desired_types:
            if security_type in self.schemes:
                return self.schemes[security_type]

        raise exception.RFBAuthNoAvailableScheme(
            allowed_types=", ".join([str(s) for s in self.schemes.keys()]),
            desired_types=", ".join([str(s) for s in desired_types]))
