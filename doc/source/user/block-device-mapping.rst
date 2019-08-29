..
      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

Block Device Mapping in Nova
============================

Nova has a concept of block devices that can be exposed to cloud instances.
There are several types of block devices an instance can have (we will go into
more details about this later in this document), and which ones are available
depends on a particular deployment and the usage limitations set for tenants
and users. Block device mapping is a way to organize and keep data about all of
the block devices an instance has.

When we talk about block device mapping, we usually refer to one of two things

1. API/CLI structure and syntax for specifying block devices for an instance
   boot request

2. The data structure internal to Nova that is used for recording and keeping,
   which is ultimately persisted in the block_device_mapping table. However,
   Nova internally has several "slightly" different formats for representing
   the same data. All of them are documented in the code and or presented by
   a distinct set of classes, but not knowing that they exist might trip up
   people reading the code. So in addition to BlockDeviceMapping [1]_ objects
   that mirror the database schema, we have:

   2.1 The API format - this is the set of raw key-value pairs received from
   the API client, and is almost immediately transformed into the object;
   however, some validations are done using this format. We will refer to this
   format as the 'API BDMs' from now on.

   2.2 The virt driver format - this is the format defined by the classes in
   :mod: `nova.virt.block_device`. This format is used and expected by the code
   in the various virt drivers. These classes, in addition to exposing a
   different format (mimicking the Python dict interface), also provide a place
   to bundle some functionality common to certain types of block devices (for
   example attaching volumes which has to interact with both Cinder and the
   virt driver code). We will refer to this format as 'Driver BDMs' from now
   on.

.. note::

   The maximum limit on the number of disk devices allowed to attach to
   a single server is configurable with the option
   :oslo.config:option:`compute.max_disk_devices_to_attach`.


Data format and its history
----------------------------

In the early days of Nova, block device mapping general structure closely
mirrored that of the EC2 API. During the Havana release of Nova, block device
handling code, and in turn the block device mapping structure, had work done on
improving the generality and usefulness. These improvements included exposing
additional details and features in the API. In order to facilitate this, a new
extension was added to the v2 API called `BlockDeviceMappingV2Boot` [2]_, that
added an additional `block_device_mapping_v2` field to the instance boot API
request.

Block device mapping v1 (aka legacy)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

This was the original format that supported only cinder volumes (similar to how
EC2 block devices support only EBS volumes). Every entry was keyed by device
name (we will discuss why this was problematic in its own section later on
this page), and would accept only:

* UUID of the Cinder volume or snapshot
* Type field - used only to distinguish between volumes and Cinder volume
  snapshots
* Optional size field
* Optional `delete_on_termination` flag

While all of Nova internal code only uses and stores the new data structure, we
still need to handle API requests that use the legacy format. This is handled
by the Nova API service on every request. As we will see later, since block
device mapping information can also be stored in the image metadata in Glance,
this is another place where we need to handle the v1 format. The code to handle
legacy conversions is part of the :mod: `nova.block_device` module.

Intermezzo - problem with device names
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Using device names as the primary per-instance identifier, and exposing them in
the API, is problematic for Nova mostly because several hypervisors Nova
supports with its drivers can't guarantee that the device names the guest OS
assigns are the ones the user requested from Nova. Exposing such a detail
in the public API of Nova is obviously not ideal, but it needed to stay for
backwards compatibility. It is also required for some (slightly obscure)
features around overloading a block device in a Glance image when booting an
instance [3]_.

The plan for fixing this was to allow users to not specify the device name of a
block device, and Nova will determine it (with the help of the virt driver), so
that it can still be discovered through the API and used when necessary, like
for the features mentioned above (and preferably only then).

Another use for specifying the device name was to allow the "boot from volume"
functionality, by specifying a device name that matches the root device name
for the instance (usually `/dev/vda`).

Currently (mid Liberty) users are discouraged from specifying device names
for all calls requiring or allowing block device mapping, except when trying to
override the image block device mapping on instance boot, and it will likely
remain like that in the future. Libvirt device driver will outright override
any device names passed with it's own values.

Block device mapping v2
^^^^^^^^^^^^^^^^^^^^^^^

New format was introduced in an attempt to solve issues with the original
block device mapping format discussed above, and also to allow for more
flexibility and addition of features that were not possible with the simple
format we had.

New block device mapping is a list of dictionaries containing the following
fields (in addition to the ones that were already there):

* source_type - this can have one of the following values:

  * `image`
  * `volume`
  * `snapshot`
  * `blank`

* destination_type  - this can have one of the following values:

  * `local`
  * `volume`

* guest_format - Tells Nova how/if to format the device prior to attaching,
  should be only used with blank local images. Denotes a swap disk if the value
  is `swap`.

* device_name - See the previous section for a more in depth explanation of
  this - currently best left empty (not specified that is), unless the user
  wants to override the existing device specified in the image metadata.
  In case of Libvirt, even when passed in with the purpose of overriding the
  existing image metadata, final set of device names for the instance may still
  get changed by the driver.

* disk_bus and device_type - low level details that some hypervisors (currently
  only libvirt) may support. Some example disk_bus values can be: `ide`, `usb`,
  `virtio`, `scsi`, while device_type may be `disk`, `cdrom`, `floppy`, `lun`.
  This is not an exhaustive list as it depends on the virtualization driver,
  and may change as more support is added. Leaving these empty is the most
  common thing to do.

* boot_index - Defines the order in which a hypervisor will try devices when
  attempting to boot the guest from storage. Each device which is capable of
  being used as boot device should be given a unique boot index, starting from
  0 in ascending order. Some hypervisors may not support booting from multiple
  devices, so will only consider the device with boot index of 0. Some
  hypervisors will support booting from multiple devices, but only if they are
  of different types - eg a disk and CD-ROM. Setting a negative value or None
  indicates that the device should not be used for booting. The simplest
  usage is to set it to 0 for the boot device and leave it as None for any
  other devices.

* volume_type - Added in microversion 2.67 to the servers create API to
  support specifying volume type when booting instances. When we snapshot a
  volume-backed server, the block_device_mapping_v2 image metadata will
  include the volume_type from the BDM record so if the user then creates
  another server from that snapshot, the volume that nova creates from that
  snapshot will use the same volume_type. If a user wishes to change that
  volume type in the image metadata, they can do so via the image API.

Valid source / destination combinations
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Combination of the ``source_type`` and ``destination_type`` will define the
kind of block device the entry is referring to. The following
combinations are supported:

* `image` -> `local` - this is only currently reserved for the entry
  referring to the Glance image that the instance is being booted with
  (it should also be marked as a boot device). It is also worth noting
  that an API request that specifies this, also has to provide the
  same Glance uuid as the `image_ref` parameter to the boot request
  (this is done for backwards compatibility and may be changed in the
  future). This functionality might be extended to specify additional
  Glance images to be attached to an instance after boot (similar to
  kernel/ramdisk images) but this functionality is not supported by
  any of the current drivers.
* `volume` -> `volume` - this is just a Cinder volume to be attached to the
  instance. It can be marked as a boot device.
* `snapshot` -> `volume` - this works exactly as passing `type=snap` does.
  It would create a volume from a Cinder volume snapshot and attach that
  volume to the instance. Can be marked bootable.
* `image` -> `volume` - As one would imagine, this would download a Glance
  image to a cinder volume and attach it to an instance. Can also be marked
  as bootable. This is really only a shortcut for creating a volume out of
  an image before booting an instance with the newly created volume.
* `blank` -> `volume` - Creates a blank Cinder volume and attaches it. This
  will also require the volume size to be set.
* `blank` -> `local` - Depending on the guest_format field (see below),
  this will either mean an ephemeral blank disk on hypervisor local
  storage, or a swap disk (instances can have only one of those).


Nova will not allow mixing of BDMv1 and BDMv2 in a single request, and
will do basic validation to make sure that the requested block device
mapping is valid before accepting a boot request.

.. [1] In addition to the BlockDeviceMapping Nova object, we also have the
   BlockDeviceDict class in :mod: `nova.block_device` module. This class
   handles transforming and validating the API BDM format.
.. [2] This work predates API microversions and thus the only way to add it was
   by means of an API extension.
.. [3] This is a feature that the EC2 API offers as well and has been in Nova
   for a long time, although it has been broken in several releases. More info
   can be found on `this bug <https://launchpad.net/bugs/1370250>`


FAQs
----

1. Is it possible to configure nova to automatically use cinder to back all
   root disks with volumes?

   No, there is nothing automatic within nova that converts a
   non-boot-from-volume request to convert the image to a root volume.
   Several ideas have been discussed over time which are captured in the
   spec for `volume-backed flavors`_. However, if you wish to force users
   to always create volume-backed servers, you can configure the API service
   by setting :oslo.config:option:`max_local_block_devices` to 0. This will
   result in any non-boot-from-volume server create request to fail with a
   400 response.

.. _volume-backed flavors: https://review.opendev.org/511965/
