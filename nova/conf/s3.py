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
               deprecated_for_removal=True,
               deprecated_since='14.0.0',
               deprecated_reason='EC2 API related options are not supported.',
               default='/tmp',
               help="""
Parent directory for tempdir used for image decryption
"""),
    cfg.StrOpt('s3_host',
               deprecated_for_removal=True,
               deprecated_since='14.0.0',
               deprecated_reason='EC2 API related options are not supported.',
               default='$my_ip',
               help="""
Hostname or IP for OpenStack to use when accessing the S3 API
"""),
    cfg.PortOpt('s3_port',
               deprecated_for_removal=True,
               deprecated_since='14.0.0',
               deprecated_reason='EC2 API related options are not supported.',
               default=3333,
               help="""
Port used when accessing the S3 API. It should be in the range of
1 - 65535
"""),
    cfg.StrOpt('s3_access_key',
               deprecated_for_removal=True,
               deprecated_since='14.0.0',
               deprecated_reason='EC2 API related options are not supported.',
               default='notchecked',
               help='Access key to use S3 server for images'),
    cfg.StrOpt('s3_secret_key',
               deprecated_for_removal=True,
               deprecated_since='14.0.0',
               deprecated_reason='EC2 API related options are not supported.',
               default='notchecked',
               help='Secret key to use for S3 server for images'),
    cfg.BoolOpt('s3_use_ssl',
                deprecated_for_removal=True,
                deprecated_since='14.0.0',
                deprecated_reason='EC2 API related options are not supported.',
                default=False,
                help='Whether to use SSL when talking to S3'),
    cfg.BoolOpt('s3_affix_tenant',
                deprecated_for_removal=True,
                deprecated_since='14.0.0',
                deprecated_reason='EC2 API related options are not supported.',
                default=False,
                help="""
Whether to affix the tenant id to the access key when downloading from S3
"""),
]


def register_opts(conf):
    conf.register_opts(s3_opts)


def list_opts():
    return {'DEFAULT': s3_opts}
