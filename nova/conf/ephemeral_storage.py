# Copyright 2015 Huawei Technology corp.
# Copyright 2015 OpenStack Foundation
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

ephemeral_storage_encryption_group = cfg.OptGroup(
    name='ephemeral_storage_encryption',
    title='Ephemeral storage encryption options')

ephemeral_storage_encryption_opts = [
    cfg.BoolOpt('enabled',
                default=False,
                help='Whether to encrypt ephemeral storage'),
    cfg.StrOpt('cipher',
               default='aes-xts-plain64',
               help='The cipher and mode to be used to encrypt ephemeral '
                    'storage. Which ciphers are available ciphers depends '
                    'on kernel support. See /proc/crypto for the list of '
                    'available options.'),
    cfg.IntOpt('key_size',
               default=512,
               help='The bit length of the encryption key to be used to '
                    'encrypt ephemeral storage (in XTS mode only half of '
                    'the bits are used for encryption key)')
]


def register_opts(conf):
    conf.register_group(ephemeral_storage_encryption_group)
    conf.register_opts(ephemeral_storage_encryption_opts,
                       group='ephemeral_storage_encryption')


def list_opts():
    return {'ephemeral_storage_encryption': ephemeral_storage_encryption_opts}
