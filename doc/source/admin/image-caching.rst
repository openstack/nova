=============
Image Caching
=============

Nova supports caching base images on compute nodes when using a
`supported virt driver`_.

.. _supported virt driver: https://docs.openstack.org/nova/latest/user/support-matrix.html#operation_cache_images

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
documentation for the configuration options in the
:oslo.config:group:`image_cache` group.

.. note::

   Some ephemeral backend drivers may not use or need image caching,
   or may not behave in the same way as others. For example, when
   using the ``rbd`` backend with the ``libvirt`` driver and a shared
   pool with glance, images are COW'd at the storage level and thus
   need not be downloaded (and thus cached) at the compute node at
   all.

Image pre-caching
-----------------

It may be beneficial to pre-cache images on compute nodes in order to
achieve low time-to-boot latency for new instances immediately. This
is often useful when rolling out a new version of an application where
downtime is important and having the new images already available on
the compute nodes is critical.

Nova provides (since the Ussuri release) a mechanism to request that
images be cached without having to boot an actual instance on a
node. This best-effort service operates at the host aggregate level in
order to provide an efficient way to indicate that a large number of
computes should receive a given set of images. If the computes that
should pre-cache an image are not already in a defined host aggregate,
that must be done first.

For information on how to perform aggregate-based image pre-caching,
see the :ref:`image-caching-aggregates` section of the Host aggregates
documentation.
