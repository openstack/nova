# Copyright 2016 OpenStack Foundation
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

from oslo_config import cfg

exc_log_opts = [
    cfg.BoolOpt('fatal_exception_format_errors',
                default=False,
                deprecated_for_removal=True,
                deprecated_since="14.0.0",
                deprecated_reason="This is only used for internal testing.",
                help="""
When set to true, this option enables validation of exception
message format.

This option is used to detect errors in NovaException class when it formats
error messages. If True, raise an exception; if False, use the unformatted
message.
""")
]


def register_opts(conf):
    conf.register_opts(exc_log_opts)


def list_opts():
    return {'DEFAULT': exc_log_opts}
