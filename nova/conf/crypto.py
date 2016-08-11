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

import os

from oslo_config import cfg

from nova.conf import paths

crypto_opts_group = cfg.OptGroup("crypto",
        title="Crypto Options")

crypto_opts = [
    cfg.StrOpt("ca_file",
        default="cacert.pem",
        deprecated_group="DEFAULT",
        help="""
Filename of root CA (Certificate Authority). This is a container format
and includes root certificates.

Possible values:

* Any file name containing root CA, cacert.pem is default

Related options:

* ca_path
"""),
    cfg.StrOpt("key_file",
        default=os.path.join("private", "cakey.pem"),
        deprecated_group="DEFAULT",
        help="""
Filename of a private key.

Related options:

* keys_path
"""),
    cfg.StrOpt("crl_file",
        default="crl.pem",
        deprecated_group="DEFAULT",
        help="""
Filename of root Certificate Revocation List (CRL). This is a list of
certificates that have been revoked, and therefore, entities presenting
those (revoked) certificates should no longer be trusted.

Related options:

* ca_path
"""),
    cfg.StrOpt("keys_path",
        default=paths.state_path_def("keys"),
        deprecated_group="DEFAULT",
        help="""
Directory path where keys are located.

Related options:

* key_file
"""),
    cfg.StrOpt("ca_path",
        default=paths.state_path_def("CA"),
        deprecated_group="DEFAULT",
        help="""
Directory path where root CA is located.

Related options:

* ca_file
"""),
    cfg.BoolOpt("use_project_ca",
        default=False,
        deprecated_group="DEFAULT",
        help="Option to enable/disable use of CA for each project."),
    cfg.StrOpt("user_cert_subject",
        default="/C=US/ST=California/O=OpenStack/"
                "OU=NovaDev/CN=%.16s-%.16s-%s",
        deprecated_group="DEFAULT",
        help="""
Subject for certificate for users, %s for
project, user, timestamp
"""),
    cfg.StrOpt("project_cert_subject",
        default="/C=US/ST=California/O=OpenStack/"
                "OU=NovaDev/CN=project-ca-%.16s-%s",
        deprecated_group="DEFAULT",
        help="""
Subject for certificate for projects, %s for
project, timestamp
"""),
]


def register_opts(conf):
    conf.register_group(crypto_opts_group)
    conf.register_opts(crypto_opts, crypto_opts_group)


def list_opts():
    return {crypto_opts_group: crypto_opts}
