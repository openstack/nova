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

glance_group = cfg.OptGroup(
    'glance',
    title='Glance Options',
    help='Configuration options for the Image service')

glance_opts = [
    # NOTE(sdague): there is intentionally no default here. This
    # requires configuration. Eventually this will come from the
    # service catalog, however we don't have a good path there atm.
    # TODO(raj_singh): Add "required=True" flag to this option.
    cfg.ListOpt('api_servers',
        help="""
List of glance api servers endpoints available to nova.

https is used for ssl-based glance api servers.

Possible values:

* A list of any fully qualified url of the form "scheme://hostname:port[/path]"
  (i.e. "http://10.0.1.0:9292" or "https://my.glance.server/image").
"""),
    cfg.BoolOpt('api_insecure',
        default=False,
        help="""
Enable insecure SSL (https) requests to glance.

This setting can be used to turn off verification of the glance server
certificate against the certificate authorities.
"""),
    cfg.IntOpt('num_retries',
        default=0,
        min=0,
        help="""
Enable glance operation retries.

Specifies the number of retries when uploading / downloading
an image to / from glance. 0 means no retries.
"""),
    cfg.ListOpt('allowed_direct_url_schemes',
        default=[],
        help="""
List of url schemes that can be directly accessed.

This option specifies a list of url schemes that can be downloaded
directly via the direct_url. This direct_URL can be fetched from
Image metadata which can be used by nova to get the
image more efficiently. nova-compute could benefit from this by
invoking a copy when it has access to the same file system as glance.

Possible values:

* [file], Empty list (default)
"""),
    cfg.BoolOpt('verify_glance_signatures',
        default=False,
        help="""
Enable image signature verification.

nova uses the image signature metadata from glance and verifies the signature
of a signed image while downloading that image. If the image signature cannot
be verified or if the image signature metadata is either incomplete or
unavailable, then nova will not boot the image and instead will place the
instance into an error state. This provides end users with stronger assurances
of the integrity of the image data they are using to create servers.

Related options:

* The options in the `key_manager` group, as the key_manager is used
  for the signature validation.
"""),
    cfg.BoolOpt('debug',
         default=False,
         help='Enable or disable debug logging with glanceclient.')
]


def register_opts(conf):
    conf.register_group(glance_group)
    conf.register_opts(glance_opts, group=glance_group)


def list_opts():
    return {glance_group: glance_opts}
