# Copyright (c) 2016 VMware Inc.
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
import sys

from oslo_log import log as logging

from nova.cmd import baseproxy
import nova.conf
from nova.conf import mks
from nova import config
from nova.console.securityproxy.mks import MksSecurityProxy


CONF = nova.conf.CONF
LOG = logging.getLogger(__name__)
mks.register_cli_opts(CONF)


def main():
    config.parse_args(sys.argv)

    if CONF.mks.verbose:
        LOG.setLevel(logging.DEBUG)
    if CONF.mks.web:
        CONF.web = CONF.mks.web

    baseproxy.proxy(
        host=CONF.mks.host,
        port=CONF.mks.port,
        security_proxy=MksSecurityProxy())
