# Copyright 2012 Grid Dynamics
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

import collections
import functools
import os

import fixtures
import mock

from nova.virt.libvirt import config
from nova.virt.libvirt import driver
from nova.virt.libvirt import imagebackend
from nova.virt.libvirt import utils as libvirt_utils


class ImageBackendFixture(fixtures.Fixture):
    def __init__(self, got_files=None, imported_files=None, exists=None):
        """This fixture mocks imagebackend.Backend.backend, which is the
        only entry point to libvirt.imagebackend from libvirt.driver.

        :param got_files: A list of {'filename': path, 'size': size} for every
                         file which was created.
        :param imported_files: A list of (local_filename, remote_filename) for
                               every invocation of import_file().
        :param exists: An optional lambda which takes the disk name as an
                       argument, and returns True if the disk exists,
                       False otherwise.
        """
        self.got_files = got_files
        self.imported_files = imported_files

        self.disks = collections.defaultdict(self._mock_disk)
        """A dict of name -> Mock image object. This is a defaultdict,
        so tests may access it directly before a disk has been created."""

        self._exists = exists

    def setUp(self):
        super(ImageBackendFixture, self).setUp()

        # Mock template functions passed to cache
        self.mock_fetch_image = mock.create_autospec(libvirt_utils.fetch_image)
        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.utils.fetch_image', self.mock_fetch_image))

        self.mock_fetch_raw_image = \
            mock.create_autospec(libvirt_utils.fetch_raw_image)
        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.utils.fetch_raw_image',
            self.mock_fetch_raw_image))

        self.mock_create_ephemeral = \
            mock.create_autospec(driver.LibvirtDriver._create_ephemeral)
        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.driver.LibvirtDriver._create_ephemeral',
            self.mock_create_ephemeral))

        self.mock_create_swap = \
            mock.create_autospec(driver.LibvirtDriver._create_swap)
        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.driver.LibvirtDriver._create_swap',
            self.mock_create_swap))

        # Backend.backend creates all Image objects
        self.useFixture(fixtures.MonkeyPatch(
            'nova.virt.libvirt.imagebackend.Backend.backend',
            self._mock_backend))

    @property
    def created_disks(self):
        """disks, filtered to contain only disks which were actually created
        by calling a relevant method.
        """

        # A disk was created iff either cache() or import_file() was called.
        return {name: disk for name, disk in self.disks.items()
                if any([disk.cache.called, disk.import_file.called])}

    def _mock_disk(self):
        # This is the generator passed to the disks defaultdict. It returns
        # a mocked Image object, but note that the returned object has not
        # yet been 'constructed'. We don't know at this stage what arguments
        # will be passed to the constructor, so we don't know, eg, its type
        # or path.
        #
        # The reason for this 2 phase construction is to allow tests to
        # manipulate mocks for disks before they have been created. eg a
        # test can do the following before executing the method under test:
        #
        #  disks['disk'].cache.side_effect = ImageNotFound...
        #
        # When the 'constructor' (image_init in _mock_backend) later runs,
        # it will return the same object we created here, and when the
        # caller calls cache() it will raise the requested exception.

        disk = mock.create_autospec(imagebackend.Image)

        # NOTE(mdbooth): fake_cache and fake_import_file are for compatibility
        # with existing tests which test got_files and imported_files. They
        # should be removed when they have no remaining users.
        disk.cache.side_effect = self._fake_cache
        disk.import_file.side_effect = self._fake_import_file

        # NOTE(mdbooth): test_virt_drivers assumes libvirt_info has functional
        # output
        disk.libvirt_info.side_effect = \
            functools.partial(self._fake_libvirt_info, disk)

        return disk

    def _mock_backend(self, backend_self, image_type=None):
        # This method mocks Backend.backend, which returns a subclass of Image
        # (it returns a class, not an instance). This mocked method doesn't
        # return a class; it returns a function which returns a Mock. IOW,
        # instead of the getting a QCow2, the caller gets image_init,
        # so instead of:
        #
        #  QCow2(instance, disk_name='disk')
        #
        # the caller effectively does:
        #
        #  image_init(instance, disk_name='disk')
        #
        # Therefore image_init() must have the same signature as an Image
        # subclass constructor, and return a mocked Image object.
        #
        # The returned mocked Image object has the following additional
        # properties which are useful for testing:
        #
        # * Calls with the same disk_name return the same object from
        #   self.disks. This means tests can assert on multiple calls for
        #   the same disk without worrying about whether they were also on
        #   the same object.
        #
        # * Mocked objects have an additional image_type attribute set to
        #   the image_type originally passed to Backend.backend() during
        #   their construction. Tests can use this to assert that disks were
        #   created of the expected type.

        def image_init(instance=None, disk_name=None, path=None):
            # There's nothing special about this path except that it's
            # predictable and unique for (instance, disk).
            if path is None:
                path = os.path.join(
                    libvirt_utils.get_instance_path(instance), disk_name)
            else:
                disk_name = os.path.basename(path)

            disk = self.disks[disk_name]

            # Used directly by callers. These would have been set if called
            # the real constructor.
            setattr(disk, 'path', path)
            setattr(disk, 'is_block_dev', mock.sentinel.is_block_dev)

            # Used by tests. Note that image_init is a closure over image_type.
            setattr(disk, 'image_type', image_type)

            # Used by tests to manipulate which disks exist.
            if self._exists is not None:
                # We don't just cache the return value here because the
                # caller may want, eg, a test where the disk initially does not
                # exist and later exists.
                disk.exists.side_effect = lambda: self._exists(disk_name)
            else:
                disk.exists.return_value = True

            return disk

        # Set the SUPPORTS_CLONE member variable to mimic the Image base
        # class.
        image_init.SUPPORTS_CLONE = False

        # Ditto for the 'is_shared_block_storage' function
        def is_shared_block_storage():
            return False

        setattr(image_init, 'is_shared_block_storage', is_shared_block_storage)

        return image_init

    def _fake_cache(self, fetch_func, filename, size=None, *args, **kwargs):
        # Execute the template function so we can test the arguments it was
        # called with.
        fetch_func(target=filename, *args, **kwargs)

        # For legacy tests which use got_files
        if self.got_files is not None:
            self.got_files.append({'filename': filename, 'size': size})

    def _fake_import_file(self, instance, local_filename, remote_filename):
        # For legacy tests which use imported_files
        if self.imported_files is not None:
            self.imported_files.append((local_filename, remote_filename))

    def _fake_libvirt_info(self, mock_disk, disk_info, cache_mode,
                           extra_specs, hypervisor_version, disk_unit=None,
                           boot_order=None):
        # For tests in test_virt_drivers which expect libvirt_info to be
        # functional
        info = config.LibvirtConfigGuestDisk()
        info.source_type = 'file'
        info.source_device = disk_info['type']
        info.target_bus = disk_info['bus']
        info.target_dev = disk_info['dev']
        info.driver_cache = cache_mode
        info.driver_format = 'raw'
        info.source_path = mock_disk.path
        if boot_order:
            info.boot_order = boot_order
        return info
