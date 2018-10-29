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

from os import path
from subprocess import check_output

import nova.conf
from nova.conf import shellinabox
from nova import config
from nova.console import shellinaboxproxy

CONF = nova.conf.CONF
shellinabox.register_cli_opts(CONF)


def main():
    """Parses cli arguments and starts mitmproxy with token validation.
    """

    if shellinaboxproxy.__file__.endswith('c'):
        script = shellinaboxproxy.__file__[:-1]
    else:
        script = shellinaboxproxy.__file__

    config.parse_args(sys.argv)
    # Run mitmproxy with shellinaboxproxy.py as an inline script
    check_output("mitmdump -R %s --port %s --bind-address %s --script %s" % (
                 CONF.shellinabox.proxyclient_url,
                 CONF.shellinabox.port,
                 CONF.shellinabox.host,
                 path.abspath(script)), shell=True)
