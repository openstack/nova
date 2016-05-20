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
    title='Glance Options')

glance_opts = [
    # NOTE(sdague): there is intentionally no default here. This
    # requires configuration. Eventually this will come from the
    # service catalog, however we don't have a good path there atm.
    cfg.ListOpt('api_servers',
                help='''
A list of the glance api servers endpoints available to nova. These
should be fully qualified urls of the form
"scheme://hostname:port[/path]" (i.e. "http://10.0.1.0:9292" or
"https://my.glance.server/image")'''),
    cfg.BoolOpt('api_insecure',
                default=False,
                help='Allow to perform insecure SSL (https) requests to '
                     'glance'),
    cfg.IntOpt('num_retries',
               default=0,
               help='Number of retries when uploading / downloading an image '
                    'to / from glance.'),
    cfg.ListOpt('allowed_direct_url_schemes',
                default=[],
                help='A list of url scheme that can be downloaded directly '
                     'via the direct_url.  Currently supported schemes: '
                     '[file].'),
    cfg.BoolOpt('verify_glance_signatures',
                default=False,
                help='Require Nova to perform signature verification on '
                     'each image downloaded from Glance.'),
    ]


def register_opts(conf):
    conf.register_group(glance_group)
    conf.register_opts(glance_opts, group=glance_group)


def list_opts():
    return {glance_group: glance_opts}
