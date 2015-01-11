# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
# Copyright (c) 2010 Citrix Systems, Inc.
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
Helper methods to deal with images.
"""

import re

from oslo_utils import strutils

from nova.openstack.common._i18n import _


class QemuImgInfo(object):
    BACKING_FILE_RE = re.compile((r"^(.*?)\s*\(actual\s+path\s*:"
                                  r"\s+(.*?)\)\s*$"), re.I)
    TOP_LEVEL_RE = re.compile(r"^([\w\d\s\_\-]+):(.*)$")
    SIZE_RE = re.compile(r"(\d*\.?\d+)(\w+)?(\s*\(\s*(\d+)\s+bytes\s*\))?",
                         re.I)

    def __init__(self, cmd_output=None):
        details = self._parse(cmd_output or '')
        self.image = details.get('image')
        self.backing_file = details.get('backing_file')
        self.file_format = details.get('file_format')
        self.virtual_size = details.get('virtual_size')
        self.cluster_size = details.get('cluster_size')
        self.disk_size = details.get('disk_size')
        self.snapshots = details.get('snapshot_list', [])
        self.encrypted = details.get('encrypted')

    def __str__(self):
        lines = [
            'image: %s' % self.image,
            'file_format: %s' % self.file_format,
            'virtual_size: %s' % self.virtual_size,
            'disk_size: %s' % self.disk_size,
            'cluster_size: %s' % self.cluster_size,
            'backing_file: %s' % self.backing_file,
        ]
        if self.snapshots:
            lines.append("snapshots: %s" % self.snapshots)
        if self.encrypted:
            lines.append("encrypted: %s" % self.encrypted)
        return "\n".join(lines)

    def _canonicalize(self, field):
        # Standardize on underscores/lc/no dash and no spaces
        # since qemu seems to have mixed outputs here... and
        # this format allows for better integration with python
        # - i.e. for usage in kwargs and such...
        field = field.lower().strip()
        for c in (" ", "-"):
            field = field.replace(c, '_')
        return field

    def _extract_bytes(self, details):
        # Replace it with the byte amount
        real_size = self.SIZE_RE.search(details)
        if not real_size:
            raise ValueError(_('Invalid input value "%s".') % details)
        magnitude = real_size.group(1)
        unit_of_measure = real_size.group(2)
        bytes_info = real_size.group(3)
        if bytes_info:
            return int(real_size.group(4))
        elif not unit_of_measure:
            return int(magnitude)
        return strutils.string_to_bytes('%s%sB' % (magnitude, unit_of_measure),
                                        return_int=True)

    def _extract_details(self, root_cmd, root_details, lines_after):
        real_details = root_details
        if root_cmd == 'backing_file':
            # Replace it with the real backing file
            backing_match = self.BACKING_FILE_RE.match(root_details)
            if backing_match:
                real_details = backing_match.group(2).strip()
        elif root_cmd in ['virtual_size', 'cluster_size', 'disk_size']:
            # Replace it with the byte amount (if we can convert it)
            if root_details == 'None':
                real_details = 0
            else:
                real_details = self._extract_bytes(root_details)
        elif root_cmd == 'file_format':
            real_details = real_details.strip().lower()
        elif root_cmd == 'snapshot_list':
            # Next line should be a header, starting with 'ID'
            if not lines_after or not lines_after.pop(0).startswith("ID"):
                msg = _("Snapshot list encountered but no header found!")
                raise ValueError(msg)
            real_details = []
            # This is the sprintf pattern we will try to match
            # "%-10s%-20s%7s%20s%15s"
            # ID TAG VM SIZE DATE VM CLOCK (current header)
            while lines_after:
                line = lines_after[0]
                line_pieces = line.split()
                if len(line_pieces) != 6:
                    break
                # Check against this pattern in the final position
                # "%02d:%02d:%02d.%03d"
                date_pieces = line_pieces[5].split(":")
                if len(date_pieces) != 3:
                    break
                lines_after.pop(0)
                real_details.append({
                    'id': line_pieces[0],
                    'tag': line_pieces[1],
                    'vm_size': line_pieces[2],
                    'date': line_pieces[3],
                    'vm_clock': line_pieces[4] + " " + line_pieces[5],
                })
        return real_details

    def _parse(self, cmd_output):
        # Analysis done of qemu-img.c to figure out what is going on here
        # Find all points start with some chars and then a ':' then a newline
        # and then handle the results of those 'top level' items in a separate
        # function.
        #
        # TODO(harlowja): newer versions might have a json output format
        #                 we should switch to that whenever possible.
        #                 see: http://bit.ly/XLJXDX
        contents = {}
        lines = [x for x in cmd_output.splitlines() if x.strip()]
        while lines:
            line = lines.pop(0)
            top_level = self.TOP_LEVEL_RE.match(line)
            if top_level:
                root = self._canonicalize(top_level.group(1))
                if not root:
                    continue
                root_details = top_level.group(2).strip()
                details = self._extract_details(root, root_details, lines)
                contents[root] = details
        return contents
