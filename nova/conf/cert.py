# Copyright 2016 IBM Corp.
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

cert_topic_opt = cfg.StrOpt("cert_topic",
        default="cert",
        help="""
Determines the RPC topic that the cert nodes listen on. The default is 'cert',
and for most deployments there is no need to ever change it.

Possible values:

Any string.

* Services which consume this:

    ``nova-cert``

* Related options:

    None
""")

rpcapi_cap_opt = cfg.StrOpt("cert",
        help="""
Specifies the maximum version for messages sent from cert services. This should
be the minimum value that is supported by all of the deployed cert services.

Possible values:

Any valid OpenStack release name, in lower case, such as 'mitaka' or 'liberty'.
Alternatively, it can be any string representing a version number in the format
'N.N'; for example, possible values might be '1.12' or '2.0'.

* Services which consume this:

    ``nova-cert``

* Related options:

    None
""")


def register_opts(conf):
    conf.register_opts([cert_topic_opt])
    conf.register_opt(rpcapi_cap_opt, "upgrade_levels")


def list_opts():
    return {"DEFAULT": [cert_topic_opt],
            "upgrade_levels": [rpcapi_cap_opt]}
