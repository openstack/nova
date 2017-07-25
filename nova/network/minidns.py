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

from oslo_config import cfg
from oslo_log import log as logging
import six

from nova import exception
from nova.i18n import _
from nova.network import dns_driver


CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class MiniDNS(dns_driver.DNSDriver):
    """Trivial DNS driver. This will read/write to either a local,
    flat file or an in memory StringIO and have no effect on your actual
    DNS system. This class is strictly for testing purposes, and should
    keep you out of dependency hell.

    A file is used when CONF.log_dir is set. This is relevant for when
    two different DNS driver instances share the same data file.

    Note that there is almost certainly a race condition here that
    will manifest anytime instances are rapidly created and deleted.
    A proper implementation will need some manner of locking.
    """

    def __init__(self):
        filename = None
        if CONF.log_dir:
            filename = os.path.join(CONF.log_dir, "dnstest.txt")
            self.file = open(filename, 'w+')
        else:
            self.file = six.StringIO()
        if not filename or not os.path.exists(filename):
            self.file.write("#  minidns\n\n\n")
            self.file.flush()

    def get_domains(self):
        entries = []
        self.file.seek(0)
        for line in self.file:
            entry = self.parse_line(line)
            if entry and entry['address'] == 'domain':
                entries.append(entry['name'])
        return entries

    def qualify(self, name, domain):
        if domain:
            qualified = "%s.%s" % (name, domain)
        else:
            qualified = name

        return qualified.lower()

    def create_entry(self, name, address, type, domain):
        if name is None:
            raise exception.InvalidInput(_("Invalid name"))

        if type.lower() != 'a':
            raise exception.InvalidInput(_("This driver only supports "
                                           "type 'a'"))

        if self.get_entries_by_name(name, domain):
            raise exception.FloatingIpDNSExists(name=name, domain=domain)

        self.file.seek(0, os.SEEK_END)
        self.file.write("%s   %s   %s\n" %
                        (address, self.qualify(name, domain), type))
        self.file.flush()

    def parse_line(self, line):
        vals = line.split()
        if len(vals) < 3:
            return None
        else:
            entry = {}
            entry['address'] = vals[0].lower()
            entry['name'] = vals[1].lower()
            entry['type'] = vals[2].lower()
            if entry['address'] == 'domain':
                entry['domain'] = entry['name']
            else:
                entry['domain'] = entry['name'].partition('.')[2]
            return entry

    def delete_entry(self, name, domain):
        if name is None:
            raise exception.InvalidInput(_("Invalid name"))

        deleted = False
        keeps = []
        self.file.seek(0)
        for line in self.file:
            entry = self.parse_line(line)
            if (not entry or
                    entry['name'] != self.qualify(name, domain)):
                keeps.append(line)
            else:
                deleted = True
        self.file.truncate(0)
        self.file.seek(0)
        self.file.write(''.join(keeps))
        self.file.flush()
        if not deleted:
            LOG.warning('Cannot delete entry |%s|', self.qualify(name, domain))
            raise exception.NotFound

    def modify_address(self, name, address, domain):

        if not self.get_entries_by_name(name, domain):
            raise exception.NotFound

        lines = []
        self.file.seek(0)
        for line in self.file:
            entry = self.parse_line(line)
            if (entry and
                    entry['name'] == self.qualify(name, domain)):
                lines.append("%s   %s   %s\n" %
                    (address, self.qualify(name, domain), entry['type']))
            else:
                lines.append(line)
        self.file.truncate(0)
        self.file.seek(0)
        self.file.write(''.join(lines))
        self.file.flush()

    def get_entries_by_address(self, address, domain):
        entries = []
        self.file.seek(0)
        for line in self.file:
            entry = self.parse_line(line)
            if entry and entry['address'] == address.lower():
                if entry['name'].endswith(domain.lower()):
                    name = entry['name'].split(".")[0]
                    if name not in entries:
                        entries.append(name)

        return entries

    def get_entries_by_name(self, name, domain):
        entries = []
        self.file.seek(0)
        for line in self.file:
            entry = self.parse_line(line)
            if (entry and
                    entry['name'] == self.qualify(name, domain)):
                entries.append(entry['address'])
        return entries

    def delete_dns_file(self):
        self.file.close()
        try:
            if os.path.exists(self.file.name):
                try:
                    os.remove(self.file.name)
                except OSError:
                    pass
        except AttributeError:
            # This was a BytesIO, which has no name.
            pass

    def create_domain(self, fqdomain):
        if self.get_entries_by_name(fqdomain, ''):
            raise exception.FloatingIpDNSExists(name=fqdomain, domain='')

        self.file.seek(0, os.SEEK_END)
        self.file.write("%s   %s   %s\n" % ('domain', fqdomain, 'domain'))
        self.file.flush()

    def delete_domain(self, fqdomain):
        deleted = False
        keeps = []
        self.file.seek(0)
        for line in self.file:
            entry = self.parse_line(line)
            if (not entry or
                    entry['domain'] != fqdomain.lower()):
                keeps.append(line)
            else:
                LOG.info("deleted %s", entry)
                deleted = True
        self.file.truncate(0)
        self.file.seek(0)
        self.file.write(''.join(keeps))
        self.file.flush()
        if not deleted:
            LOG.warning('Cannot delete domain |%s|', fqdomain)
            raise exception.NotFound
