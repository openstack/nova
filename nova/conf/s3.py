# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

s3_opts = [
    cfg.StrOpt('image_decryption_dir',
               default='/tmp',
               help='Parent directory for tempdir used for image decryption'),
    cfg.StrOpt('s3_host',
               default='$my_ip',
               help='Hostname or IP for OpenStack to use when accessing '
                    'the S3 api'),
    cfg.IntOpt('s3_port',
               default=3333,
               min=1,
               max=65535,
               help='Port used when accessing the S3 api'),
    cfg.StrOpt('s3_access_key',
               default='notchecked',
               help='Access key to use for S3 server for images'),
    cfg.StrOpt('s3_secret_key',
               default='notchecked',
               help='Secret key to use for S3 server for images'),
    cfg.BoolOpt('s3_use_ssl',
                default=False,
                help='Whether to use SSL when talking to S3'),
    cfg.BoolOpt('s3_affix_tenant',
                default=False,
                help='Whether to affix the tenant id to the access key '
                     'when downloading from S3'),
    ]


def register_opts(conf):
    conf.register_opts(s3_opts)


def list_opts():
    return {'DEFAULT': s3_opts}
