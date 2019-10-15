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

imagecache_group = cfg.OptGroup(
    'image_cache',
    title='Image Cache Options',
    help="""
A collection of options specific to image caching.
""")
imagecache_opts = [
    cfg.IntOpt('precache_concurrency',
               default=1,
               min=1,
               help="""
Maximum number of compute hosts to trigger image precaching in parallel.

When an image precache request is made, compute nodes will be contacted
to initiate the download. This number constrains the number of those that
will happen in parallel. Higher numbers will cause more computes to work
in parallel and may result in reduced time to complete the operation, but
may also DDoS the image service. Lower numbers will result in more sequential
operation, lower image service load, but likely longer runtime to completion.
"""),
]


ALL_OPTS = (imagecache_opts,)


def register_opts(conf):
    conf.register_group(imagecache_group)
    conf.register_opts(imagecache_opts, group=imagecache_group)


def list_opts():
    return {imagecache_group: imagecache_opts}
