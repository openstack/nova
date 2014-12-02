# Copyright 2013 OpenStack Foundation
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

from oslo.config import cfg

from nova.compute import task_states
from nova.compute import vm_states
from nova import objects
from nova.virt import block_device as driver_block_device

imagecache_opts = [
    cfg.IntOpt('image_cache_manager_interval',
               default=2400,
               help='Number of seconds to wait between runs of the image '
                    'cache manager. Set to -1 to disable. '
                    'Setting this to 0 will run at the default rate.'),
    cfg.StrOpt('image_cache_subdirectory_name',
               default='_base',
               help='Where cached images are stored under $instances_path. '
                    'This is NOT the full path - just a folder name. '
                    'For per-compute-host cached images, set to _base_$my_ip'),
    cfg.BoolOpt('remove_unused_base_images',
                default=True,
                help='Should unused base images be removed?'),
    cfg.IntOpt('remove_unused_original_minimum_age_seconds',
               default=(24 * 3600),
               help='Unused unresized base images younger than this will not '
                    'be removed'),
    ]

CONF = cfg.CONF
CONF.register_opts(imagecache_opts)
CONF.import_opt('host', 'nova.netconf')


class ImageCacheManager(object):
    """Base class for the image cache manager.

    This class will provide a generic interface to the image cache manager.
    """

    def __init__(self):
        self.remove_unused_base_images = CONF.remove_unused_base_images
        self.resize_states = [task_states.RESIZE_PREP,
                              task_states.RESIZE_MIGRATING,
                              task_states.RESIZE_MIGRATED,
                              task_states.RESIZE_FINISH]

    def _get_base(self):
        """Returns the base directory of the cached images."""
        raise NotImplementedError()

    def _list_running_instances(self, context, all_instances):
        """List running instances (on all compute nodes).

        This method returns a dictionary with the following keys:
            - used_images
            - image_popularity
            - instance_names
        """
        used_images = {}
        image_popularity = {}
        instance_names = set()
        used_swap_images = set()

        for instance in all_instances:
            # NOTE(mikal): "instance name" here means "the name of a directory
            # which might contain an instance" and therefore needs to include
            # historical permutations as well as the current one.
            instance_names.add(instance.name)
            instance_names.add(instance.uuid)
            if (instance.task_state in self.resize_states or
                    instance.vm_state == vm_states.RESIZED):
                instance_names.add(instance.name + '_resize')
                instance_names.add(instance.uuid + '_resize')

            for image_key in ['image_ref', 'kernel_id', 'ramdisk_id']:
                image_ref_str = getattr(instance, image_key)
                if image_ref_str is None:
                    continue
                local, remote, insts = used_images.get(image_ref_str,
                                                            (0, 0, []))
                if instance.host == CONF.host:
                    local += 1
                else:
                    remote += 1
                insts.append(instance.name)
                used_images[image_ref_str] = (local, remote, insts)

                image_popularity.setdefault(image_ref_str, 0)
                image_popularity[image_ref_str] += 1

            gb = objects.BlockDeviceMappingList.get_by_instance_uuid
            bdms = gb(context, instance.uuid)
            if bdms:
                swap = driver_block_device.convert_swap(bdms)
                if swap:
                    swap_image = 'swap_' + str(swap[0]['swap_size'])
                    used_swap_images.add(swap_image)

        return {'used_images': used_images,
                'image_popularity': image_popularity,
                'instance_names': instance_names,
                'used_swap_images': used_swap_images}

    def _list_base_images(self, base_dir):
        """Return a list of the images present in _base.

        This method returns a dictionary with the following keys:
            - unexplained_images
            - originals
        """
        return {'unexplained_images': [],
                'originals': []}

    def _age_and_verify_cached_images(self, context, all_instances, base_dir):
        """Ages and verifies cached images."""

        raise NotImplementedError()

    def update(self, context, all_instances):
        """The cache manager.

        This will invoke the cache manager. This will update the cache
        according to the defined cache management scheme. The information
        populated in the cached stats will be used for the cache management.
        """
        raise NotImplementedError()
