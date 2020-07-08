=============
Image Caching
=============

What is Image Caching?
----------------------

In order to understand what image caching is and why it is beneficial,
it helps to be familiar with the process by which an instance is
booted from a given base image. When a new instance is created on a
compute node, the following general steps are performed by the compute
manager in conjunction with the virt driver:

#. Download the base image from glance
#. Copy or COW the base image to create a new root disk image for the instance
#. Boot the instance using the new root disk image

The first step involves downloading the entire base image to the local
disk on the compute node, which could involve many gigabytes of
network traffic, storage, and many minutes of latency between the
start of the boot process and actually running the instance. When the
virt driver supports image caching, step #1 above may be skipped if
the base image is already present on the compute node. This is most
often the case when another instance has been booted on that node from
the same base image recently. If present, the download operation can
be skipped, which greatly reduces the time-to-boot for the second and
subsequent instances that use the same base image, as well as avoids
load on the glance server and the network connection.

By default, the compute node will periodically scan the images it has
cached, looking for base images that are not used by any instances on
the node that are older than a configured lifetime (24 hours by
default). Those unused images are deleted from the cache directory
until they are needed again.

For more information about configuring image cache behavior, see the
documentation for the following configuration options:

- :oslo.config:option:`image_cache_subdirectory_name`
- :oslo.config:option:`image_cache_manager_interval`
- :oslo.config:option:`remove_unused_base_images`
- :oslo.config:option:`remove_unused_original_minimum_age_seconds`

.. note::

   Some ephemeral backend drivers may not use or need image caching,
   or may not behave in the same way as others. For example, when
   using the ``rbd`` backend with the ``libvirt`` driver and a shared
   pool with glance, images are COW'd at the storage level and thus
   need not be downloaded (and thus cached) at the compute node at
   all.

Image Caching Resource Accounting
---------------------------------

Generally the size of the image cache is not part of the data Nova
includes when reporting available or consumed disk space. This means
that when ``nova-compute`` reports 100G of total disk space, the
scheduler will assume that 100G of instances may be placed
there. Usually disk is the most plentiful resource and thus the last
to be exhausted, so this is often not problematic. However, if many
instances are booted from distinct images, all of which need to be
cached in addition to the disk space used by the instances themselves,
Nova may overcommit the disk unintentionally by failing to consider
the size of the image cache.

There are two approaches to addressing this situation:

#. **Mount the image cache as a separate filesystem**. This will
   cause Nova to report the amount of disk space available purely to
   instances, independent of how much is consumed by the cache. Nova
   will continue to disregard the size of the image cache and, if the
   cache space is exhausted, builds will fail. However, available
   disk space for instances will be correctly reported by
   ``nova-compute`` and accurately considered by the scheduler.

#. **Enable optional reserved disk amount behavior**.  The
   configuration workaround
   :oslo.config:option:`workarounds.reserve_disk_resource_for_image_cache`
   will cause ``nova-compute`` to periodically update the reserved disk
   amount to include the statically configured value, as well as the
   amount currently consumed by the image cache. This will cause the
   scheduler to see the available disk space decrease as the image
   cache grows. This is not updated synchronously and thus is not a
   perfect solution, but should vastly increase the scheduler's
   visibility resulting in better decisions. (Note this solution is
   currently libvirt-specific)

As above, not all backends and virt drivers use image caching, and
thus a third option may be to consider alternative infrastructure to
eliminate this problem altogether.
