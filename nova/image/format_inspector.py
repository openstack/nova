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

"""
This is a python implementation of virtual disk format inspection routines
gathered from various public specification documents, as well as qemu disk
driver code. It attempts to store and parse the minimum amount of data
required, and in a streaming-friendly manner to collect metadata about
complex-format images.
"""

import struct

from oslo_log import log as logging
from oslo_utils import units

LOG = logging.getLogger(__name__)


def chunked_reader(fileobj, chunk_size=512):
    while True:
        chunk = fileobj.read(chunk_size)
        if not chunk:
            break
        yield chunk


class CaptureRegion(object):
    """Represents a region of a file we want to capture.

    A region of a file we want to capture requires a byte offset into
    the file and a length. This is expected to be used by a data
    processing loop, calling capture() with the most recently-read
    chunk. This class handles the task of grabbing the desired region
    of data across potentially multiple fractional and unaligned reads.

    :param offset: Byte offset into the file starting the region
    :param length: The length of the region
    """

    def __init__(self, offset, length):
        self.offset = offset
        self.length = length
        self.data = b''

    @property
    def complete(self):
        """Returns True when we have captured the desired data."""
        return self.length == len(self.data)

    def capture(self, chunk, current_position):
        """Process a chunk of data.

        This should be called for each chunk in the read loop, at least
        until complete returns True.

        :param chunk: A chunk of bytes in the file
        :param current_position: The position of the file processed by the
                                 read loop so far. Note that this will be
                                 the position in the file *after* the chunk
                                 being presented.
        """
        read_start = current_position - len(chunk)
        if (read_start <= self.offset <= current_position or
                self.offset <= read_start <= (self.offset + self.length)):
            if read_start < self.offset:
                lead_gap = self.offset - read_start
            else:
                lead_gap = 0
            self.data += chunk[lead_gap:]
            self.data = self.data[:self.length]


class ImageFormatError(Exception):
    """An unrecoverable image format error that aborts the process."""
    pass


class TraceDisabled(object):
    """A logger-like thing that swallows tracing when we do not want it."""

    def debug(self, *a, **k):
        pass

    info = debug
    warning = debug
    error = debug


class FileInspector(object):
    """A stream-based disk image inspector.

    This base class works on raw images and is subclassed for more
    complex types. It is to be presented with the file to be examined
    one chunk at a time, during read processing and will only store
    as much data as necessary to determine required attributes of
    the file.
    """

    def __init__(self, tracing=False):
        self._total_count = 0

        # NOTE(danms): The logging in here is extremely verbose for a reason,
        # but should never really be enabled at that level at runtime. To
        # retain all that work and assist in future debug, we have a separate
        # debug flag that can be passed from a manual tool to turn it on.
        if tracing:
            self._log = logging.getLogger(str(self))
        else:
            self._log = TraceDisabled()
        self._capture_regions = {}

    def _capture(self, chunk, only=None):
        for name, region in self._capture_regions.items():
            if only and name not in only:
                continue
            if not region.complete:
                region.capture(chunk, self._total_count)

    def eat_chunk(self, chunk):
        """Call this to present chunks of the file to the inspector."""
        pre_regions = set(self._capture_regions.keys())

        # Increment our position-in-file counter
        self._total_count += len(chunk)

        # Run through the regions we know of to see if they want this
        # data
        self._capture(chunk)

        # Let the format do some post-read processing of the stream
        self.post_process()

        # Check to see if the post-read processing added new regions
        # which may require the current chunk.
        new_regions = set(self._capture_regions.keys()) - pre_regions
        if new_regions:
            self._capture(chunk, only=new_regions)

    def post_process(self):
        """Post-read hook to process what has been read so far.

        This will be called after each chunk is read and potentially captured
        by the defined regions. If any regions are defined by this call,
        those regions will be presented with the current chunk in case it
        is within one of the new regions.
        """
        pass

    def region(self, name):
        """Get a CaptureRegion by name."""
        return self._capture_regions[name]

    def new_region(self, name, region):
        """Add a new CaptureRegion by name."""
        if self.has_region(name):
            # This is a bug, we tried to add the same region twice
            raise ImageFormatError('Inspector re-added region %s' % name)
        self._capture_regions[name] = region

    def has_region(self, name):
        """Returns True if named region has been defined."""
        return name in self._capture_regions

    @property
    def format_match(self):
        """Returns True if the file appears to be the expected format."""
        return True

    @property
    def virtual_size(self):
        """Returns the virtual size of the disk image, or zero if unknown."""
        return self._total_count

    @property
    def actual_size(self):
        """Returns the total size of the file, usually smaller than
        virtual_size. NOTE: this will only be accurate if the entire
        file is read and processed.
        """
        return self._total_count

    @property
    def complete(self):
        """Returns True if we have all the information needed."""
        return all(r.complete for r in self._capture_regions.values())

    def __str__(self):
        """The string name of this file format."""
        return 'raw'

    @property
    def context_info(self):
        """Return info on amount of data held in memory for auditing.

        This is a dict of region:sizeinbytes items that the inspector
        uses to examine the file.
        """
        return {name: len(region.data) for name, region in
                self._capture_regions.items()}

    @classmethod
    def from_file(cls, filename):
        """Read as much of a file as necessary to complete inspection.

        NOTE: Because we only read as much of the file as necessary, the
        actual_size property will not reflect the size of the file, but the
        amount of data we read before we satisfied the inspector.

        Raises ImageFormatError if we cannot parse the file.
        """
        inspector = cls()
        with open(filename, 'rb') as f:
            for chunk in chunked_reader(f):
                inspector.eat_chunk(chunk)
                if inspector.complete:
                    # No need to eat any more data
                    break
        if not inspector.complete or not inspector.format_match:
            raise ImageFormatError('File is not in requested format')
        return inspector

    def safety_check(self):
        """Perform some checks to determine if this file is safe.

        Returns True if safe, False otherwise. It may raise ImageFormatError
        if safety cannot be guaranteed because of parsing or other errors.
        """
        return True


# The qcow2 format consists of a big-endian 72-byte header, of which
# only a small portion has information we care about:
#
# Dec   Hex   Name
#   0  0x00   Magic 4-bytes 'QFI\xfb'
#   4  0x04   Version (uint32_t, should always be 2 for modern files)
#  . . .
#   8  0x08   Backing file offset (uint64_t)
#  24  0x18   Size in bytes (unint64_t)
#  . . .
#  72  0x48   Incompatible features bitfield (6 bytes)
#
# https://gitlab.com/qemu-project/qemu/-/blob/master/docs/interop/qcow2.txt
class QcowInspector(FileInspector):
    """QEMU QCOW2 Format

    This should only require about 32 bytes of the beginning of the file
    to determine the virtual size, and 104 bytes to perform the safety check.
    """

    BF_OFFSET = 0x08
    BF_OFFSET_LEN = 8
    I_FEATURES = 0x48
    I_FEATURES_LEN = 8
    I_FEATURES_DATAFILE_BIT = 3
    I_FEATURES_MAX_BIT = 4

    def __init__(self, *a, **k):
        super(QcowInspector, self).__init__(*a, **k)
        self.new_region('header', CaptureRegion(0, 512))

    def _qcow_header_data(self):
        magic, version, bf_offset, bf_sz, cluster_bits, size = (
            struct.unpack('>4sIQIIQ', self.region('header').data[:32]))
        return magic, size

    @property
    def has_header(self):
        return self.region('header').complete

    @property
    def virtual_size(self):
        if not self.region('header').complete:
            return 0
        if not self.format_match:
            return 0
        magic, size = self._qcow_header_data()
        return size

    @property
    def format_match(self):
        if not self.region('header').complete:
            return False
        magic, size = self._qcow_header_data()
        return magic == b'QFI\xFB'

    @property
    def has_backing_file(self):
        if not self.region('header').complete:
            return None
        if not self.format_match:
            return False
        bf_offset_bytes = self.region('header').data[
            self.BF_OFFSET:self.BF_OFFSET + self.BF_OFFSET_LEN]
        # nonzero means "has a backing file"
        bf_offset, = struct.unpack('>Q', bf_offset_bytes)
        return bf_offset != 0

    @property
    def has_unknown_features(self):
        if not self.region('header').complete:
            return None
        if not self.format_match:
            return False
        i_features = self.region('header').data[
            self.I_FEATURES:self.I_FEATURES + self.I_FEATURES_LEN]

        # This is the maximum byte number we should expect any bits to be set
        max_byte = self.I_FEATURES_MAX_BIT // 8

        # The flag bytes are in big-endian ordering, so if we process
        # them in index-order, they're reversed
        for i, byte_num in enumerate(reversed(range(self.I_FEATURES_LEN))):
            if byte_num == max_byte:
                # If we're in the max-allowed byte, allow any bits less than
                # the maximum-known feature flag bit to be set
                allow_mask = ((1 << self.I_FEATURES_MAX_BIT) - 1)
            elif byte_num > max_byte:
                # If we're above the byte with the maximum known feature flag
                # bit, then we expect all zeroes
                allow_mask = 0x0
            else:
                # Any earlier-than-the-maximum byte can have any of the flag
                # bits set
                allow_mask = 0xFF

            if i_features[i] & ~allow_mask:
                LOG.warning('Found unknown feature bit in byte %i: %s/%s',
                            byte_num, bin(i_features[byte_num] & ~allow_mask),
                            bin(allow_mask))
                return True

        return False

    @property
    def has_data_file(self):
        if not self.region('header').complete:
            return None
        if not self.format_match:
            return False
        i_features = self.region('header').data[
            self.I_FEATURES:self.I_FEATURES + self.I_FEATURES_LEN]

        # First byte of bitfield, which is i_features[7]
        byte = self.I_FEATURES_LEN - 1 - self.I_FEATURES_DATAFILE_BIT // 8
        # Third bit of bitfield, which is 0x04
        bit = 1 << (self.I_FEATURES_DATAFILE_BIT - 1 % 8)
        return bool(i_features[byte] & bit)

    def __str__(self):
        return 'qcow2'

    def safety_check(self):
        return (not self.has_backing_file and
                not self.has_data_file and
                not self.has_unknown_features)


class QEDInspector(FileInspector):
    def __init__(self, tracing=False):
        super().__init__(tracing)
        self.new_region('header', CaptureRegion(0, 512))

    @property
    def format_match(self):
        if not self.region('header').complete:
            return False
        return self.region('header').data.startswith(b'QED\x00')

    def safety_check(self):
        # QED format is not supported by anyone, but we want to detect it
        # and mark it as just always unsafe.
        return False


# The VHD (or VPC as QEMU calls it) format consists of a big-endian
# 512-byte "footer" at the beginning of the file with various
# information, most of which does not matter to us:
#
# Dec   Hex   Name
#   0  0x00   Magic string (8-bytes, always 'conectix')
#  40  0x28   Disk size (uint64_t)
#
# https://github.com/qemu/qemu/blob/master/block/vpc.c
class VHDInspector(FileInspector):
    """Connectix/MS VPC VHD Format

    This should only require about 512 bytes of the beginning of the file
    to determine the virtual size.
    """

    def __init__(self, *a, **k):
        super(VHDInspector, self).__init__(*a, **k)
        self.new_region('header', CaptureRegion(0, 512))

    @property
    def format_match(self):
        return self.region('header').data.startswith(b'conectix')

    @property
    def virtual_size(self):
        if not self.region('header').complete:
            return 0

        if not self.format_match:
            return 0

        return struct.unpack('>Q', self.region('header').data[40:48])[0]

    def __str__(self):
        return 'vhd'


# The VHDX format consists of a complex dynamic little-endian
# structure with multiple regions of metadata and data, linked by
# offsets with in the file (and within regions), identified by MSFT
# GUID strings. The header is a 320KiB structure, only a few pieces of
# which we actually need to capture and interpret:
#
#     Dec    Hex  Name
#      0 0x00000  Identity (Technically 9-bytes, padded to 64KiB, the first
#                 8 bytes of which are 'vhdxfile')
# 196608 0x30000  The Region table (64KiB of a 32-byte header, followed
#                 by up to 2047 36-byte region table entry structures)
#
# The region table header includes two items we need to read and parse,
# which are:
#
# 196608 0x30000  4-byte signature ('regi')
# 196616 0x30008  Entry count (uint32-t)
#
# The region table entries follow the region table header immediately
# and are identified by a 16-byte GUID, and provide an offset of the
# start of that region. We care about the "metadata region", identified
# by the METAREGION class variable. The region table entry is (offsets
# from the beginning of the entry, since it could be in multiple places):
#
#      0 0x00000 16-byte MSFT GUID
#     16 0x00010 Offset of the actual metadata region (uint64_t)
#
# When we find the METAREGION table entry, we need to grab that offset
# and start examining the region structure at that point. That
# consists of a metadata table of structures, which point to places in
# the data in an unstructured space that follows. The header is
# (offsets relative to the region start):
#
#      0 0x00000 8-byte signature ('metadata')
#      . . .
#     16 0x00010 2-byte entry count (up to 2047 entries max)
#
# This header is followed by the specified number of metadata entry
# structures, identified by GUID:
#
#      0 0x00000 16-byte MSFT GUID
#     16 0x00010 4-byte offset (uint32_t, relative to the beginning of
#                the metadata region)
#
# We need to find the "Virtual Disk Size" metadata item, identified by
# the GUID in the VIRTUAL_DISK_SIZE class variable, grab the offset,
# add it to the offset of the metadata region, and examine that 8-byte
# chunk of data that follows.
#
# The "Virtual Disk Size" is a naked uint64_t which contains the size
# of the virtual disk, and is our ultimate target here.
#
# https://docs.microsoft.com/en-us/openspecs/windows_protocols/ms-vhdx/83e061f8-f6e2-4de1-91bd-5d518a43d477
class VHDXInspector(FileInspector):
    """MS VHDX Format

    This requires some complex parsing of the stream. The first 256KiB
    of the image is stored to get the header and region information,
    and then we capture the first metadata region to read those
    records, find the location of the virtual size data and parse
    it. This needs to store the metadata table entries up until the
    VDS record, which may consist of up to 2047 32-byte entries at
    max.  Finally, it must store a chunk of data at the offset of the
    actual VDS uint64.

    """
    METAREGION = '8B7CA206-4790-4B9A-B8FE-575F050F886E'
    VIRTUAL_DISK_SIZE = '2FA54224-CD1B-4876-B211-5DBED83BF4B8'
    VHDX_METADATA_TABLE_MAX_SIZE = 32 * 2048  # From qemu

    def __init__(self, *a, **k):
        super(VHDXInspector, self).__init__(*a, **k)
        self.new_region('ident', CaptureRegion(0, 32))
        self.new_region('header', CaptureRegion(192 * 1024, 64 * 1024))

    def post_process(self):
        # After reading a chunk, we may have the following conditions:
        #
        # 1. We may have just completed the header region, and if so,
        #    we need to immediately read and calculate the location of
        #    the metadata region, as it may be starting in the same
        #    read we just did.
        # 2. We may have just completed the metadata region, and if so,
        #    we need to immediately calculate the location of the
        #    "virtual disk size" record, as it may be starting in the
        #    same read we just did.
        if self.region('header').complete and not self.has_region('metadata'):
            region = self._find_meta_region()
            if region:
                self.new_region('metadata', region)
        elif self.has_region('metadata') and not self.has_region('vds'):
            region = self._find_meta_entry(self.VIRTUAL_DISK_SIZE)
            if region:
                self.new_region('vds', region)

    @property
    def format_match(self):
        return self.region('ident').data.startswith(b'vhdxfile')

    @staticmethod
    def _guid(buf):
        """Format a MSFT GUID from the 16-byte input buffer."""
        guid_format = '<IHHBBBBBBBB'
        return '%08X-%04X-%04X-%02X%02X-%02X%02X%02X%02X%02X%02X' % (
            struct.unpack(guid_format, buf))

    def _find_meta_region(self):
        # The region table entries start after a 16-byte table header
        region_entry_first = 16

        # Parse the region table header to find the number of regions
        regi, cksum, count, reserved = struct.unpack(
            '<IIII', self.region('header').data[:16])
        if regi != 0x69676572:
            raise ImageFormatError('Region signature not found at %x' % (
                self.region('header').offset))

        if count >= 2048:
            raise ImageFormatError('Region count is %i (limit 2047)' % count)

        # Process the regions until we find the metadata one; grab the
        # offset and return
        self._log.debug('Region entry first is %x', region_entry_first)
        self._log.debug('Region entries %i', count)
        meta_offset = 0
        for i in range(0, count):
            entry_start = region_entry_first + (i * 32)
            entry_end = entry_start + 32
            entry = self.region('header').data[entry_start:entry_end]
            self._log.debug('Entry offset is %x', entry_start)

            # GUID is the first 16 bytes
            guid = self._guid(entry[:16])
            if guid == self.METAREGION:
                # This entry is the metadata region entry
                meta_offset, meta_len, meta_req = struct.unpack(
                    '<QII', entry[16:])
                self._log.debug('Meta entry %i specifies offset: %x',
                                i, meta_offset)
                # NOTE(danms): The meta_len in the region descriptor is the
                # entire size of the metadata table and data. This can be
                # very large, so we should only capture the size required
                # for the maximum length of the table, which is one 32-byte
                # table header, plus up to 2047 32-byte entries.
                meta_len = 2048 * 32
                return CaptureRegion(meta_offset, meta_len)

        self._log.warning('Did not find metadata region')
        return None

    def _find_meta_entry(self, desired_guid):
        meta_buffer = self.region('metadata').data
        if len(meta_buffer) < 32:
            # Not enough data yet for full header
            return None

        # Make sure we found the metadata region by checking the signature
        sig, reserved, count = struct.unpack('<8sHH', meta_buffer[:12])
        if sig != b'metadata':
            raise ImageFormatError(
                'Invalid signature for metadata region: %r' % sig)

        entries_size = 32 + (count * 32)
        if len(meta_buffer) < entries_size:
            # Not enough data yet for all metadata entries. This is not
            # strictly necessary as we could process whatever we have until
            # we find the V-D-S one, but there are only 2047 32-byte
            # entries max (~64k).
            return None

        if count >= 2048:
            raise ImageFormatError(
                'Metadata item count is %i (limit 2047)' % count)

        for i in range(0, count):
            entry_offset = 32 + (i * 32)
            guid = self._guid(meta_buffer[entry_offset:entry_offset + 16])
            if guid == desired_guid:
                # Found the item we are looking for by id.
                # Stop our region from capturing
                item_offset, item_length, _reserved = struct.unpack(
                    '<III',
                    meta_buffer[entry_offset + 16:entry_offset + 28])
                item_length = min(item_length,
                                  self.VHDX_METADATA_TABLE_MAX_SIZE)
                self.region('metadata').length = len(meta_buffer)
                self._log.debug('Found entry at offset %x', item_offset)
                # Metadata item offset is from the beginning of the metadata
                # region, not the file.
                return CaptureRegion(
                    self.region('metadata').offset + item_offset,
                    item_length)

        self._log.warning('Did not find guid %s', desired_guid)
        return None

    @property
    def virtual_size(self):
        # Until we have found the offset and have enough metadata buffered
        # to read it, return "unknown"
        if not self.has_region('vds') or not self.region('vds').complete:
            return 0

        size, = struct.unpack('<Q', self.region('vds').data)
        return size

    def __str__(self):
        return 'vhdx'


# The VMDK format comes in a large number of variations, but the
# single-file 'monolithicSparse' version 4 one is mostly what we care
# about. It contains a 512-byte little-endian header, followed by a
# variable-length "descriptor" region of text. The header looks like:
#
#   Dec  Hex  Name
#     0 0x00  4-byte magic string 'KDMV'
#     4 0x04  Version (uint32_t)
#     8 0x08  Flags (uint32_t, unused by us)
#    16 0x10  Number of 512 byte sectors in the disk (uint64_t)
#    24 0x18  Granularity (uint64_t, unused by us)
#    32 0x20  Descriptor offset in 512-byte sectors (uint64_t)
#    40 0x28  Descriptor size in 512-byte sectors (uint64_t)
#
# After we have the header, we need to find the descriptor region,
# which starts at the sector identified in the "descriptor offset"
# field, and is "descriptor size" 512-byte sectors long. Once we have
# that region, we need to parse it as text, looking for the
# createType=XXX line that specifies the mechanism by which the data
# extents are stored in this file. We only support the
# "monolithicSparse" format, so we just need to confirm that this file
# contains that specifier.
#
# https://www.vmware.com/app/vmdk/?src=vmdk
class VMDKInspector(FileInspector):
    """vmware VMDK format (monolithicSparse and streamOptimized variants only)

    This needs to store the 512 byte header and the descriptor region
    which should be just after that. The descriptor region is some
    variable number of 512 byte sectors, but is just text defining the
    layout of the disk.
    """

    # The beginning and max size of the descriptor is also hardcoded in Qemu
    # at 0x200 and 1MB - 1
    DESC_OFFSET = 0x200
    DESC_MAX_SIZE = (1 << 20) - 1
    GD_AT_END = 0xffffffffffffffff

    def __init__(self, *a, **k):
        super(VMDKInspector, self).__init__(*a, **k)
        self.new_region('header', CaptureRegion(0, 512))

    def post_process(self):
        # If we have just completed the header region, we need to calculate
        # the location and length of the descriptor, which should immediately
        # follow and may have been partially-read in this read.
        if not self.region('header').complete:
            return

        (sig, ver, _flags, _sectors, _grain, desc_sec, desc_num,
         _numGTEsperGT, _rgdOffset, gdOffset) = struct.unpack(
            '<4sIIQQQQIQQ', self.region('header').data[:64])

        if sig != b'KDMV':
            raise ImageFormatError('Signature KDMV not found: %r' % sig)

        if ver not in (1, 2, 3):
            raise ImageFormatError('Unsupported format version %i' % ver)

        if gdOffset == self.GD_AT_END:
            # This means we have a footer, which takes precedence over the
            # header, which we cannot support since we stream.
            raise ImageFormatError('Unsupported VMDK footer')

        # Since we parse both desc_sec and desc_num (the location of the
        # VMDK's descriptor, expressed in 512 bytes sectors) we enforce a
        # check on the bounds to create a reasonable CaptureRegion. This
        # is similar to how it's done in qemu.
        desc_offset = desc_sec * 512
        desc_size = min(desc_num * 512, self.DESC_MAX_SIZE)
        if desc_offset != self.DESC_OFFSET:
            raise ImageFormatError("Wrong descriptor location")

        if not self.has_region('descriptor'):
            self.new_region('descriptor', CaptureRegion(
                desc_offset, desc_size))

    @property
    def format_match(self):
        return self.region('header').data.startswith(b'KDMV')

    @property
    def virtual_size(self):
        if not self.has_region('descriptor'):
            # Not enough data yet
            return 0

        descriptor_rgn = self.region('descriptor')
        if not descriptor_rgn.complete:
            # Not enough data yet
            return 0

        descriptor = descriptor_rgn.data
        type_idx = descriptor.index(b'createType="') + len(b'createType="')
        type_end = descriptor.find(b'"', type_idx)
        # Make sure we don't grab and log a huge chunk of data in a
        # maliciously-formatted descriptor region
        if type_end - type_idx < 64:
            vmdktype = descriptor[type_idx:type_end]
        else:
            vmdktype = b'formatnotfound'
        if vmdktype not in (b'monolithicSparse', b'streamOptimized'):
            LOG.warning('Unsupported VMDK format %s', vmdktype)
            return 0

        # If we have the descriptor, we definitely have the header
        _sig, _ver, _flags, sectors, _grain, _desc_sec, _desc_num = (
            struct.unpack('<IIIQQQQ', self.region('header').data[:44]))

        return sectors * 512

    def safety_check(self):
        if (not self.has_region('descriptor') or
                not self.region('descriptor').complete):
            return False

        try:
            # Descriptor is padded to 512 bytes
            desc_data = self.region('descriptor').data.rstrip(b'\x00')
            # Descriptor is actually case-insensitive ASCII text
            desc_text = desc_data.decode('ascii').lower()
        except UnicodeDecodeError:
            LOG.error('VMDK descriptor failed to decode as ASCII')
            raise ImageFormatError('Invalid VMDK descriptor data')

        extent_access = ('rw', 'rdonly', 'noaccess')
        header_fields = []
        extents = []
        ddb = []

        # NOTE(danms): Cautiously parse the VMDK descriptor. Each line must
        # be something we understand, otherwise we refuse it.
        for line in [x.strip() for x in desc_text.split('\n')]:
            if line.startswith('#') or not line:
                # Blank or comment lines are ignored
                continue
            elif line.startswith('ddb'):
                # DDB lines are allowed (but not used by us)
                ddb.append(line)
            elif '=' in line and ' ' not in line.split('=')[0]:
                # Header fields are a single word followed by an '=' and some
                # value
                header_fields.append(line)
            elif line.split(' ')[0] in extent_access:
                # Extent lines start with one of the three access modes
                extents.append(line)
            else:
                # Anything else results in a rejection
                LOG.error('Unsupported line %r in VMDK descriptor', line)
                raise ImageFormatError('Invalid VMDK descriptor data')

        # Check all the extent lines for concerning content
        for extent_line in extents:
            if '/' in extent_line:
                LOG.error('Extent line %r contains unsafe characters',
                          extent_line)
                return False

        if not extents:
            LOG.error('VMDK file specified no extents')
            return False

        return True

    def __str__(self):
        return 'vmdk'


# The VirtualBox VDI format consists of a 512-byte little-endian
# header, some of which we care about:
#
#  Dec   Hex  Name
#   64  0x40  4-byte Magic (0xbeda107f)
#   . . .
#  368 0x170  Size in bytes (uint64_t)
#
# https://github.com/qemu/qemu/blob/master/block/vdi.c
class VDIInspector(FileInspector):
    """VirtualBox VDI format

    This only needs to store the first 512 bytes of the image.
    """

    def __init__(self, *a, **k):
        super(VDIInspector, self).__init__(*a, **k)
        self.new_region('header', CaptureRegion(0, 512))

    @property
    def format_match(self):
        if not self.region('header').complete:
            return False

        signature, = struct.unpack('<I', self.region('header').data[0x40:0x44])
        return signature == 0xbeda107f

    @property
    def virtual_size(self):
        if not self.region('header').complete:
            return 0
        if not self.format_match:
            return 0

        size, = struct.unpack('<Q', self.region('header').data[0x170:0x178])
        return size

    def __str__(self):
        return 'vdi'


class ISOInspector(FileInspector):
    """ISO 9660 and UDF format

    we need to check the first 32KB + descriptor size
    to look for the ISO 9660 or UDF signature.

    http://wiki.osdev.org/ISO_9660
    http://wiki.osdev.org/UDF
    mkisofs --help  | grep udf

    The Universal Disc Format or UDF is the filesystem used on DVDs and
    Blu-Ray discs.UDF is an extension of ISO 9660 and shares the same
    header structure and initial layout.

    Like the CDFS(ISO 9660) file system,
    the UDF file system uses a 2048 byte sector size,
    and it designates that the first 16 sectors can be used by the OS
    to store proprietary data or boot logic.

    That means we need to check the first 32KB + descriptor size
    to look for the ISO 9660 or UDF signature.
    both formats have an extent based layout, so we can't determine
    ahead of time where the descriptor will be located.

    fortunately, the ISO 9660 and UDF formats have a Primary Volume Descriptor
    located at the beginning of the image, which contains the volume size.

    """

    def __init__(self, *a, **k):
        super(ISOInspector, self).__init__(*a, **k)
        self.new_region('system_area', CaptureRegion(0, 32 * units.Ki))
        self.new_region('header', CaptureRegion(32 * units.Ki, 2 * units.Ki))

    @property
    def format_match(self):
        if not self.complete:
            return False
        signature = self.region('header').data[1:6]
        assert len(signature) == 5
        return signature in (b'CD001', b'NSR02', b'NSR03')

    @property
    def virtual_size(self):
        if not self.complete:
            return 0
        if not self.format_match:
            return 0

        # the header size is 2KB or 1 sector
        # the first header field is the descriptor type which is 1 byte
        # the second field is the standard identifier which is 5 bytes
        # the third field is the version which is 1 byte
        # the rest of the header contains type specific data is 2041 bytes
        # see http://wiki.osdev.org/ISO_9660#The_Primary_Volume_Descriptor

        # we need to check that the descriptor type is 1
        # to ensure that this is a primary volume descriptor
        descriptor_type = self.region('header').data[0]
        if descriptor_type != 1:
            return 0
        # The size in bytes of a logical block is stored at offset 128
        # and is 2 bytes long encoded in both little and big endian
        # int16_LSB-MSB so the field is 4 bytes long
        logical_block_size_data = self.region('header').data[128:132]
        assert len(logical_block_size_data) == 4
        # given the encoding we only need to read half the field so we
        # can use the first 2 bytes which are the little endian part
        # this is normally 2048 or 2KB but we need to check as it can be
        # different according to the ISO 9660 standard.
        logical_block_size, = struct.unpack('<H', logical_block_size_data[:2])
        # The volume space size is the total number of logical blocks
        # and is stored at offset 80 and is 8 bytes long
        # as with the logical block size the field is encoded in both
        # little and big endian as an int32_LSB-MSB
        volume_space_size_data = self.region('header').data[80:88]
        assert len(volume_space_size_data) == 8
        # given the encoding we only need to read half the field so we
        # can use the first 4 bytes which are the little endian part
        volume_space_size, = struct.unpack('<L', volume_space_size_data[:4])
        # the virtual size is the volume space size * logical block size
        return volume_space_size * logical_block_size

    def __str__(self):
        return 'iso'


class InfoWrapper(object):
    """A file-like object that wraps another and updates a format inspector.

    This passes chunks to the format inspector while reading. If the inspector
    fails, it logs the error and stops calling it, but continues proxying data
    from the source to its user.
    """

    def __init__(self, source, fmt):
        self._source = source
        self._format = fmt
        self._error = False

    def __iter__(self):
        return self

    def _process_chunk(self, chunk):
        if not self._error:
            try:
                self._format.eat_chunk(chunk)
            except Exception as e:
                # Absolutely do not allow the format inspector to break
                # our streaming of the image. If we failed, just stop
                # trying, log and keep going.
                LOG.error('Format inspector failed, aborting: %s', e)
                self._error = True

    def __next__(self):
        try:
            chunk = next(self._source)
        except StopIteration:
            raise
        self._process_chunk(chunk)
        return chunk

    def read(self, size):
        chunk = self._source.read(size)
        self._process_chunk(chunk)
        return chunk

    def close(self):
        if hasattr(self._source, 'close'):
            self._source.close()


ALL_FORMATS = {
    'raw': FileInspector,
    'qcow2': QcowInspector,
    'vhd': VHDInspector,
    'vhdx': VHDXInspector,
    'vmdk': VMDKInspector,
    'vdi': VDIInspector,
    'qed': QEDInspector,
    'iso': ISOInspector,
}


def get_inspector(format_name):
    """Returns a FormatInspector class based on the given name.

    :param format_name: The name of the disk_format (raw, qcow2, etc).
    :returns: A FormatInspector or None if unsupported.
    """

    return ALL_FORMATS.get(format_name)


def detect_file_format(filename):
    """Attempts to detect the format of a file.

    This runs through a file one time, running all the known inspectors in
    parallel. It stops reading the file once all of them matches or all of
    them are sure they don't match.

    :param filename: The path to the file to inspect.
    :returns: A FormatInspector instance matching the file.
    :raises: ImageFormatError if multiple formats are detected.
    """
    inspectors = {k: v() for k, v in ALL_FORMATS.items()}
    detections = []
    with open(filename, 'rb') as f:
        for chunk in chunked_reader(f):
            for format, inspector in list(inspectors.items()):
                try:
                    inspector.eat_chunk(chunk)
                except ImageFormatError:
                    # No match, so stop considering this format
                    inspectors.pop(format)
                    continue
                if (inspector.format_match and inspector.complete and
                        format != 'raw'):
                    # record all match (other than raw)
                    detections.append(inspector)
                    inspectors.pop(format)
            if all(i.complete for i in inspectors.values()):
                # If all the inspectors are sure they are not a match, avoid
                # reading to the end of the file to settle on 'raw'.
                break

    if len(detections) > 1:
        all_formats = [str(inspector) for inspector in detections]
        raise ImageFormatError(
            'Multiple formats detected: %s' % ', '.join(all_formats))

    return inspectors['raw'] if not detections else detections[0]
