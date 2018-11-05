# Copyright 2018 OpenStack Foundation
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


key_pairs_group = cfg.OptGroup('key_pairs',
    title='SSH key pairs options',
    help="""
Options under this group are used to define Nova SSH key pairs.
""")

crypto_opts = [
    cfg.StrOpt("fingerprint_algorithm",
        default="md5",
        choices=[
            ("md5", "Use MD5 for fingerprinting"),
            ("sha1", "Use SHA-1 for fingerprinting"),
            ("sha256", "Use SHA-256 for fingerprinting")
        ],
        help="""
This controls the hashing algorithm used for creating SSH
public key fingerprints. This should not be adjusted after
deployment or after SSH key pairs have been generated. Care
should also be taken to ensure the database column holding the
key pair fingerprint is wide enough for the resulting fingerprint.
""")
]


KEY_PAIRS_OPTS = (crypto_opts)


def register_opts(conf):
    conf.register_group(key_pairs_group)
    conf.register_opts(KEY_PAIRS_OPTS, group=key_pairs_group)


def list_opts():
    return {key_pairs_group: KEY_PAIRS_OPTS}
