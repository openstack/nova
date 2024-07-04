# Copyright 2020 Red Hat, Inc
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

import io
import os
import re
import struct
import subprocess
import tempfile
from unittest import mock

from oslo_utils import units

from nova.image import format_inspector
from nova import test


TEST_IMAGE_PREFIX = 'nova-unittest-formatinspector-'


def get_size_from_qemu_img(filename):
    output = subprocess.check_output('qemu-img info "%s"' % filename,
                                     shell=True)
    for line in output.split(b'\n'):
        m = re.search(b'^virtual size: .* .([0-9]+) bytes', line.strip())
        if m:
            return int(m.group(1))

    raise Exception('Could not find virtual size with qemu-img')


class TestFormatInspectors(test.NoDBTestCase):
    def setUp(self):
        super(TestFormatInspectors, self).setUp()
        self._created_files = []

    def tearDown(self):
        super(TestFormatInspectors, self).tearDown()
        for fn in self._created_files:
            try:
                os.remove(fn)
            except Exception:
                pass

    def _create_iso(self, image_size, subformat='iso-9660'):
        # these tests depend on mkisofs
        # being installed and in the path,
        # if it is not installed, skip
        try:
            subprocess.check_output('mkisofs --version', shell=True)
        except Exception:
            self.skipTest('mkisofs not installed')

        size = image_size // units.Mi
        base_cmd = "mkisofs"
        if subformat == 'udf':
            # depending on the distribution mkisofs may not support udf
            # and may be provided by genisoimage instead. As a result we
            # need to check if the command supports udf via help
            # instead of checking the installed version.
            # mkisofs --help outputs to stderr so we need to
            # redirect it to stdout to use grep.
            try:
                subprocess.check_output(
                    'mkisofs --help 2>&1 | grep udf', shell=True)
            except Exception:
                self.skipTest('mkisofs does not support udf format')
            base_cmd += " -udf"
        prefix = TEST_IMAGE_PREFIX
        prefix += '-%s-' % subformat
        fn = tempfile.mktemp(prefix=prefix, suffix='.iso')
        self._created_files.append(fn)
        subprocess.check_output(
            'dd if=/dev/zero of=%s bs=1M count=%i' % (fn, size),
            shell=True)
        subprocess.check_output(
            '%s -o %s -V "TEST" -J -r %s' % (base_cmd, fn, fn),
            shell=True)
        return fn

    def _create_img(self, fmt, size, subformat=None, options=None,
                    backing_file=None):
        if fmt == 'iso':
            return self._create_iso(size, subformat)

        # these tests depend on qemu-img
        # being installed and in the path,
        # if it is not installed, skip
        try:
            subprocess.check_output('qemu-img --version', shell=True)
        except Exception:
            self.skipTest('qemu-img not installed')

        if fmt == 'vhd':
            # QEMU calls the vhd format vpc
            fmt = 'vpc'

        if options is None:
            options = {}
        opt = ''
        prefix = TEST_IMAGE_PREFIX

        if subformat:
            options['subformat'] = subformat
            prefix += subformat + '-'

        if options:
            opt += '-o ' + ','.join('%s=%s' % (k, v)
                                    for k, v in options.items())

        if backing_file is not None:
            opt += ' -b %s -F raw' % backing_file

        fn = tempfile.mktemp(prefix=prefix,
                             suffix='.%s' % fmt)
        self._created_files.append(fn)
        subprocess.check_output(
            'qemu-img create -f %s %s %s %i' % (fmt, opt, fn, size),
            shell=True)
        return fn

    def _create_allocated_vmdk(self, size_mb, subformat=None):
        # We need a "big" VMDK file to exercise some parts of the code of the
        # format_inspector. A way to create one is to first create an empty
        # file, and then to convert it with the -S 0 option.

        if subformat is None:
            # Matches qemu-img default, see `qemu-img convert -O vmdk -o help`
            subformat = 'monolithicSparse'

        prefix = TEST_IMAGE_PREFIX
        prefix += '-%s-' % subformat
        fn = tempfile.mktemp(prefix=prefix, suffix='.vmdk')
        self._created_files.append(fn)
        raw = tempfile.mktemp(prefix=prefix, suffix='.raw')
        self._created_files.append(raw)

        # Create a file with pseudo-random data, otherwise it will get
        # compressed in the streamOptimized format
        subprocess.check_output(
            'dd if=/dev/urandom of=%s bs=1M count=%i' % (raw, size_mb),
            shell=True)

        # Convert it to VMDK
        subprocess.check_output(
            'qemu-img convert -f raw -O vmdk -o subformat=%s -S 0 %s %s' % (
                subformat, raw, fn),
            shell=True)
        return fn

    def _test_format_at_block_size(self, format_name, img, block_size):
        fmt = format_inspector.get_inspector(format_name)()
        self.assertIsNotNone(fmt,
                             'Did not get format inspector for %s' % (
                                 format_name))
        wrapper = format_inspector.InfoWrapper(open(img, 'rb'), fmt)

        while True:
            chunk = wrapper.read(block_size)
            if not chunk:
                break

        wrapper.close()
        return fmt

    def _test_format_at_image_size(self, format_name, image_size,
                                   subformat=None):
        img = self._create_img(format_name, image_size, subformat=subformat)

        # Some formats have internal alignment restrictions making this not
        # always exactly like image_size, so get the real value for comparison
        virtual_size = get_size_from_qemu_img(img)

        # Read the format in various sizes, some of which will read whole
        # sections in a single read, others will be completely unaligned, etc.
        for block_size in (64 * units.Ki, 512, 17, 1 * units.Mi):
            fmt = self._test_format_at_block_size(format_name, img, block_size)
            self.assertTrue(fmt.format_match,
                            'Failed to match %s at size %i block %i' % (
                                format_name, image_size, block_size))
            self.assertEqual(virtual_size, fmt.virtual_size,
                             ('Failed to calculate size for %s at size %i '
                              'block %i') % (format_name, image_size,
                                             block_size))
            memory = sum(fmt.context_info.values())
            self.assertLess(memory, 512 * units.Ki,
                            'Format used more than 512KiB of memory: %s' % (
                                fmt.context_info))

    def _test_format(self, format_name, subformat=None):
        # Try a few different image sizes, including some odd and very small
        # sizes
        for image_size in (512, 513, 2057, 7):
            self._test_format_at_image_size(format_name, image_size * units.Mi,
                                            subformat=subformat)

    def test_qcow2(self):
        self._test_format('qcow2')

    def test_iso_9660(self):
        # reproduce iso-9660 format regression
        self.assertRaises(
            TypeError, self._test_format, 'iso', subformat='iso-9660')

    def test_udf(self):
        # reproduce udf format regression
        self.assertRaises(
            TypeError, self._test_format, 'iso', subformat='udf')

    def test_vhd(self):
        self._test_format('vhd')

    def test_vhdx(self):
        self._test_format('vhdx')

    def test_vmdk(self):
        self._test_format('vmdk')

    def test_vmdk_stream_optimized(self):
        self._test_format('vmdk', 'streamOptimized')

    def test_from_file_reads_minimum(self):
        img = self._create_img('qcow2', 10 * units.Mi)
        file_size = os.stat(img).st_size
        fmt = format_inspector.QcowInspector.from_file(img)
        # We know everything we need from the first 512 bytes of a QCOW image,
        # so make sure that we did not read the whole thing when we inspect
        # a local file.
        self.assertLess(fmt.actual_size, file_size)

    def test_qed_always_unsafe(self):
        img = self._create_img('qed', 10 * units.Mi)
        fmt = format_inspector.get_inspector('qed').from_file(img)
        self.assertTrue(fmt.format_match)
        self.assertFalse(fmt.safety_check())

    def _test_vmdk_bad_descriptor_offset(self, subformat=None):
        format_name = 'vmdk'
        image_size = 10 * units.Mi
        descriptorOffsetAddr = 0x1c
        BAD_ADDRESS = 0x400
        img = self._create_img(format_name, image_size, subformat=subformat)

        # Corrupt the header
        fd = open(img, 'r+b')
        fd.seek(descriptorOffsetAddr)
        fd.write(struct.pack('<Q', BAD_ADDRESS // 512))
        fd.close()

        # Read the format in various sizes, some of which will read whole
        # sections in a single read, others will be completely unaligned, etc.
        for block_size in (64 * units.Ki, 512, 17, 1 * units.Mi):
            fmt = self._test_format_at_block_size(format_name, img, block_size)
            self.assertTrue(fmt.format_match,
                            'Failed to match %s at size %i block %i' % (
                                format_name, image_size, block_size))
            self.assertEqual(0, fmt.virtual_size,
                             ('Calculated a virtual size for a corrupt %s at '
                              'size %i block %i') % (format_name, image_size,
                                                     block_size))

    def test_vmdk_bad_descriptor_offset(self):
        self._test_vmdk_bad_descriptor_offset()

    def test_vmdk_bad_descriptor_offset_stream_optimized(self):
        self._test_vmdk_bad_descriptor_offset(subformat='streamOptimized')

    def _test_vmdk_bad_descriptor_mem_limit(self, subformat=None):
        format_name = 'vmdk'
        image_size = 5 * units.Mi
        virtual_size = 5 * units.Mi
        descriptorOffsetAddr = 0x1c
        descriptorSizeAddr = descriptorOffsetAddr + 8
        twoMBInSectors = (2 << 20) // 512
        # We need a big VMDK because otherwise we will not have enough data to
        # fill-up the CaptureRegion.
        img = self._create_allocated_vmdk(image_size // units.Mi,
                                          subformat=subformat)

        # Corrupt the end of descriptor address so it "ends" at 2MB
        fd = open(img, 'r+b')
        fd.seek(descriptorSizeAddr)
        fd.write(struct.pack('<Q', twoMBInSectors))
        fd.close()

        # Read the format in various sizes, some of which will read whole
        # sections in a single read, others will be completely unaligned, etc.
        for block_size in (64 * units.Ki, 512, 17, 1 * units.Mi):
            fmt = self._test_format_at_block_size(format_name, img, block_size)
            self.assertTrue(fmt.format_match,
                            'Failed to match %s at size %i block %i' % (
                                format_name, image_size, block_size))
            self.assertEqual(virtual_size, fmt.virtual_size,
                             ('Failed to calculate size for %s at size %i '
                              'block %i') % (format_name, image_size,
                                             block_size))
            memory = sum(fmt.context_info.values())
            self.assertLess(memory, 1.5 * units.Mi,
                            'Format used more than 1.5MiB of memory: %s' % (
                                fmt.context_info))

    def test_vmdk_bad_descriptor_mem_limit(self):
        self._test_vmdk_bad_descriptor_mem_limit()

    def test_vmdk_bad_descriptor_mem_limit_stream_optimized(self):
        self._test_vmdk_bad_descriptor_mem_limit(subformat='streamOptimized')

    def test_qcow2_safety_checks(self):
        # Create backing and data-file names (and initialize the backing file)
        backing_fn = tempfile.mktemp(prefix='backing')
        self._created_files.append(backing_fn)
        with open(backing_fn, 'w') as f:
            f.write('foobar')
        data_fn = tempfile.mktemp(prefix='data')
        self._created_files.append(data_fn)

        # A qcow with no backing or data file is safe
        fn = self._create_img('qcow2', 5 * units.Mi, None)
        inspector = format_inspector.QcowInspector.from_file(fn)
        self.assertTrue(inspector.safety_check())

        # A backing file makes it unsafe
        fn = self._create_img('qcow2', 5 * units.Mi, None,
                              backing_file=backing_fn)
        inspector = format_inspector.QcowInspector.from_file(fn)
        self.assertFalse(inspector.safety_check())

        # A data-file makes it unsafe
        fn = self._create_img('qcow2', 5 * units.Mi,
                              options={'data_file': data_fn,
                                       'data_file_raw': 'on'})
        inspector = format_inspector.QcowInspector.from_file(fn)
        self.assertFalse(inspector.safety_check())

        # Trying to load a non-QCOW file is an error
        self.assertRaises(format_inspector.ImageFormatError,
                          format_inspector.QcowInspector.from_file,
                          backing_fn)

    def test_qcow2_feature_flag_checks(self):
        data = bytearray(512)
        data[0:4] = b'QFI\xFB'
        inspector = format_inspector.QcowInspector()
        inspector.region('header').data = data

        # All zeros, no feature flags - all good
        self.assertFalse(inspector.has_unknown_features)

        # A feature flag set in the first byte (highest-order) is not
        # something we know about, so fail.
        data[0x48] = 0x01
        self.assertTrue(inspector.has_unknown_features)

        # The first bit in the last byte (lowest-order) is known (the dirty
        # bit) so that should pass
        data[0x48] = 0x00
        data[0x4F] = 0x01
        self.assertFalse(inspector.has_unknown_features)

        # Currently (as of 2024), the high-order feature flag bit in the low-
        # order byte is not assigned, so make sure we reject it.
        data[0x4F] = 0x80
        self.assertTrue(inspector.has_unknown_features)

    def test_vdi(self):
        self._test_format('vdi')

    def _test_format_with_invalid_data(self, format_name):
        fmt = format_inspector.get_inspector(format_name)()
        wrapper = format_inspector.InfoWrapper(open(__file__, 'rb'), fmt)
        while True:
            chunk = wrapper.read(32)
            if not chunk:
                break

        wrapper.close()
        self.assertFalse(fmt.format_match)
        self.assertEqual(0, fmt.virtual_size)
        memory = sum(fmt.context_info.values())
        self.assertLess(memory, 512 * units.Ki,
                        'Format used more than 512KiB of memory: %s' % (
                            fmt.context_info))

    def test_qcow2_invalid(self):
        self._test_format_with_invalid_data('qcow2')

    def test_vhd_invalid(self):
        self._test_format_with_invalid_data('vhd')

    def test_vhdx_invalid(self):
        self._test_format_with_invalid_data('vhdx')

    def test_vmdk_invalid(self):
        self._test_format_with_invalid_data('vmdk')

    def test_vdi_invalid(self):
        self._test_format_with_invalid_data('vdi')

    def test_vmdk_invalid_type(self):
        fmt = format_inspector.get_inspector('vmdk')()
        wrapper = format_inspector.InfoWrapper(open(__file__, 'rb'), fmt)
        while True:
            chunk = wrapper.read(32)
            if not chunk:
                break

        wrapper.close()

        fake_rgn = mock.MagicMock()
        fake_rgn.complete = True
        fake_rgn.data = b'foocreateType="someunknownformat"bar'

        with mock.patch.object(fmt, 'has_region', return_value=True):
            with mock.patch.object(fmt, 'region', return_value=fake_rgn):
                self.assertEqual(0, fmt.virtual_size)


class TestFormatInspectorInfra(test.NoDBTestCase):
    def _test_capture_region_bs(self, bs):
        data = b''.join(chr(x).encode() for x in range(ord('A'), ord('z')))

        regions = [
            format_inspector.CaptureRegion(3, 9),
            format_inspector.CaptureRegion(0, 256),
            format_inspector.CaptureRegion(32, 8),
        ]

        for region in regions:
            # None of them should be complete yet
            self.assertFalse(region.complete)

        pos = 0
        for i in range(0, len(data), bs):
            chunk = data[i:i + bs]
            pos += len(chunk)
            for region in regions:
                region.capture(chunk, pos)

        self.assertEqual(data[3:12], regions[0].data)
        self.assertEqual(data[0:256], regions[1].data)
        self.assertEqual(data[32:40], regions[2].data)

        # The small regions should be complete
        self.assertTrue(regions[0].complete)
        self.assertTrue(regions[2].complete)

        # This region extended past the available data, so not complete
        self.assertFalse(regions[1].complete)

    def test_capture_region(self):
        for block_size in (1, 3, 7, 13, 32, 64):
            self._test_capture_region_bs(block_size)

    def _get_wrapper(self, data):
        source = io.BytesIO(data)
        fake_fmt = mock.create_autospec(format_inspector.get_inspector('raw'))
        return format_inspector.InfoWrapper(source, fake_fmt)

    def test_info_wrapper_file_like(self):
        data = b''.join(chr(x).encode() for x in range(ord('A'), ord('z')))
        wrapper = self._get_wrapper(data)

        read_data = b''
        while True:
            chunk = wrapper.read(8)
            if not chunk:
                break
            read_data += chunk

        self.assertEqual(data, read_data)

    def test_info_wrapper_iter_like(self):
        data = b''.join(chr(x).encode() for x in range(ord('A'), ord('z')))
        wrapper = self._get_wrapper(data)

        read_data = b''
        for chunk in wrapper:
            read_data += chunk

        self.assertEqual(data, read_data)

    def test_info_wrapper_file_like_eats_error(self):
        wrapper = self._get_wrapper(b'123456')
        wrapper._format.eat_chunk.side_effect = Exception('fail')

        data = b''
        while True:
            chunk = wrapper.read(3)
            if not chunk:
                break
            data += chunk

        # Make sure we got all the data despite the error
        self.assertEqual(b'123456', data)

        # Make sure we only called this once and never again after
        # the error was raised
        wrapper._format.eat_chunk.assert_called_once_with(b'123')

    def test_info_wrapper_iter_like_eats_error(self):
        fake_fmt = mock.create_autospec(format_inspector.get_inspector('raw'))
        wrapper = format_inspector.InfoWrapper(iter([b'123', b'456']),
                                               fake_fmt)
        fake_fmt.eat_chunk.side_effect = Exception('fail')

        data = b''
        for chunk in wrapper:
            data += chunk

        # Make sure we got all the data despite the error
        self.assertEqual(b'123456', data)

        # Make sure we only called this once and never again after
        # the error was raised
        fake_fmt.eat_chunk.assert_called_once_with(b'123')

    def test_get_inspector(self):
        self.assertEqual(format_inspector.QcowInspector,
                         format_inspector.get_inspector('qcow2'))
        self.assertIsNone(format_inspector.get_inspector('foo'))


class TestFormatInspectorsTargeted(test.NoDBTestCase):
    def _make_vhd_meta(self, guid_raw, item_length):
        # Meta region header, padded to 32 bytes
        data = struct.pack('<8sHH', b'metadata', 0, 1)
        data += b'0' * 20

        # Metadata table entry, 16-byte GUID, 12-byte information,
        # padded to 32-bytes
        data += guid_raw
        data += struct.pack('<III', 256, item_length, 0)
        data += b'0' * 6

        return data

    def test_vhd_table_over_limit(self):
        ins = format_inspector.VHDXInspector()
        meta = format_inspector.CaptureRegion(0, 0)
        desired = b'012345678ABCDEF0'
        # This is a poorly-crafted image that specifies a larger table size
        # than is allowed
        meta.data = self._make_vhd_meta(desired, 33 * 2048)
        ins.new_region('metadata', meta)
        new_region = ins._find_meta_entry(ins._guid(desired))
        # Make sure we clamp to our limit of 32 * 2048
        self.assertEqual(
            format_inspector.VHDXInspector.VHDX_METADATA_TABLE_MAX_SIZE,
            new_region.length)

    def test_vhd_table_under_limit(self):
        ins = format_inspector.VHDXInspector()
        meta = format_inspector.CaptureRegion(0, 0)
        desired = b'012345678ABCDEF0'
        meta.data = self._make_vhd_meta(desired, 16 * 2048)
        ins.new_region('metadata', meta)
        new_region = ins._find_meta_entry(ins._guid(desired))
        # Table size was under the limit, make sure we get it back
        self.assertEqual(16 * 2048, new_region.length)
