# Copyright 2014 Cloudbase Solutions Srl
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

"""Module for RDP Proxying."""

from oslo_config import cfg


rdp_opts = [
    cfg.StrOpt('html5_proxy_base_url',
               default='http://127.0.0.1:6083/',
               help='Location of RDP html5 console proxy, in the form '
                    '"http://127.0.0.1:6083/"'),
    cfg.BoolOpt('enabled',
                default=False,
                help='Enable RDP related features'),
    ]

CONF = cfg.CONF
CONF.register_opts(rdp_opts, group='rdp')
