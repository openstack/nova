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
    cfg.IntOpt('manager_interval',
        default=2400,
        min=-1,
        deprecated_name='image_cache_manager_interval',
        deprecated_group='DEFAULT',
        help="""
Number of seconds to wait between runs of the image cache manager.

Note that when using shared storage for the ``[DEFAULT]/instances_path``
configuration option across multiple nova-compute services, this periodic
could process a large number of instances. Similarly, using a compute driver
that manages a cluster (like vmwareapi.VMwareVCDriver) could result in
processing a large number of instances. Therefore you may need to adjust the
time interval for the anticipated load, or only run on one nova-compute
service within a shared storage aggregate.

Possible values:

* 0: run at the default interval of 60 seconds (not recommended)
* -1: disable
* Any other value

Related options:

* ``[DEFAULT]/compute_driver``
* ``[DEFAULT]/instances_path``
"""),
    cfg.StrOpt('subdirectory_name',
        default='_base',
        deprecated_name='image_cache_subdirectory_name',
        deprecated_group='DEFAULT',
        help="""
Location of cached images.

This is NOT the full path - just a folder name relative to '$instances_path'.
For per-compute-host cached images, set to '_base_$my_ip'
"""),
    cfg.BoolOpt('remove_unused_base_images',
        default=True,
        deprecated_group='DEFAULT',
        help='Should unused base images be removed?'),
    cfg.IntOpt('remove_unused_original_minimum_age_seconds',
        default=(24 * 3600),
        deprecated_group='DEFAULT',
        help="""
Unused unresized base images younger than this will not be removed.
"""),
    cfg.IntOpt('remove_unused_resized_minimum_age_seconds',
        default=3600,
        deprecated_group='libvirt',
        help="""
Unused resized base images younger than this will not be removed.
"""),
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
