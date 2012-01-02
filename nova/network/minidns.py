# Copyright 2011 Andrew Bogott for the Wikimedia Foundation
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

import os
import shutil
import tempfile

from nova import exception
from nova import flags


class MiniDNS(object):
    """ Trivial DNS driver. This will read/write to a local, flat file
        and have no effect on your actual DNS system. This class is
        strictly for testing purposes, and should keep you out of dependency
        hell.

        Note that there is almost certainly a race condition here that
        will manifest anytime instances are rapidly created and deleted.
        A proper implementation will need some manner of locking."""

    def __init__(self):
        if flags.FLAGS.logdir:
            self.filename = os.path.join(flags.FLAGS.logdir, "dnstest.txt")
        else:
            self.filename = "dnstest.txt"

        if not os.path.exists(self.filename):
            f = open(self.filename, "w+")
            f.write("#  minidns\n\n\n")
            f.close()

    def get_zones(self):
        return flags.FLAGS.floating_ip_dns_zones

    def qualify(self, name, zone):
        if zone:
            qualified = "%s.%s" % (name, zone)
        else:
            qualified = name

        return qualified

    def create_entry(self, name, address, type, dnszone):

        if self.get_entries_by_name(name, dnszone):
            raise exception.FloatingIpDNSExists(name=name, zone=dnszone)

        outfile = open(self.filename, 'a+')
        outfile.write("%s   %s   %s\n" %
            (address, self.qualify(name, dnszone), type))
        outfile.close()

    def parse_line(self, line):
        vals = line.split()
        if len(vals) < 3:
            return None
        else:
            entry = {}
            entry['address'] = vals[0]
            entry['name'] = vals[1]
            entry['type'] = vals[2]
            return entry

    def delete_entry(self, name, dnszone=""):
        deleted = False
        infile = open(self.filename, 'r')
        outfile = tempfile.NamedTemporaryFile('w', delete=False)
        for line in infile:
            entry = self.parse_line(line)
            if ((not entry) or
                entry['name'] != self.qualify(name, dnszone).lower()):
                outfile.write(line)
            else:
                deleted = True
        infile.close()
        outfile.close()
        shutil.move(outfile.name, self.filename)
        if not deleted:
            raise exception.NotFound

    def modify_address(self, name, address, dnszone):

        if not self.get_entries_by_name(name, dnszone):
            raise exception.NotFound

        infile = open(self.filename, 'r')
        outfile = tempfile.NamedTemporaryFile('w', delete=False)
        for line in infile:
            entry = self.parse_line(line)
            if (entry and
                entry['name'].lower() == self.qualify(name, dnszone).lower()):
                outfile.write("%s   %s   %s\n" %
                    (address, self.qualify(name, dnszone), entry['type']))
            else:
                outfile.write(line)
        infile.close()
        outfile.close()
        shutil.move(outfile.name, self.filename)

    def get_entries_by_address(self, address, dnszone=""):
        entries = []
        infile = open(self.filename, 'r')
        for line in infile:
            entry = self.parse_line(line)
            if entry and entry['address'].lower() == address.lower():
                if entry['name'].lower().endswith(dnszone.lower()):
                    domain_index = entry['name'].lower().find(dnszone.lower())
                    entries.append(entry['name'][0:domain_index - 1])
        infile.close()
        return entries

    def get_entries_by_name(self, name, dnszone=""):
        entries = []
        infile = open(self.filename, 'r')
        for line in infile:
            entry = self.parse_line(line)
            if (entry and
                entry['name'].lower() == self.qualify(name, dnszone).lower()):
                entries.append(entry['address'])
        infile.close()
        return entries

    def delete_dns_file(self):
        os.remove(self.filename)
