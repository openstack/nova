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

from oslo_config import cfg
from oslo_log import log as logging

from nova import exception
from nova.i18n import _, _LI, _LW
from nova.network import dns_driver

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


class MiniDNS(dns_driver.DNSDriver):
    """Trivial DNS driver. This will read/write to a local, flat file
    and have no effect on your actual DNS system. This class is
    strictly for testing purposes, and should keep you out of dependency
    hell.

    Note that there is almost certainly a race condition here that
    will manifest anytime instances are rapidly created and deleted.
    A proper implementation will need some manner of locking.
    """

    def __init__(self):
        if CONF.log_dir:
            self.filename = os.path.join(CONF.log_dir, "dnstest.txt")
            self.tempdir = None
        else:
            self.tempdir = tempfile.mkdtemp()
            self.filename = os.path.join(self.tempdir, "dnstest.txt")
        LOG.debug('minidns file is |%s|', self.filename)

        if not os.path.exists(self.filename):
            with open(self.filename, "w+") as f:
                f.write("#  minidns\n\n\n")

    def get_domains(self):
        entries = []
        with open(self.filename, 'r') as infile:
            for line in infile:
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

        with open(self.filename, 'a+') as outfile:
            outfile.write("%s   %s   %s\n" %
                (address, self.qualify(name, domain), type))

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
        outfile = tempfile.NamedTemporaryFile('w', delete=False)
        with open(self.filename, 'r') as infile:
            for line in infile:
                entry = self.parse_line(line)
                if (not entry or
                        entry['name'] != self.qualify(name, domain)):
                    outfile.write(line)
                else:
                    deleted = True
        outfile.close()
        shutil.move(outfile.name, self.filename)
        if not deleted:
            LOG.warning(_LW('Cannot delete entry |%s|'),
                        self.qualify(name, domain))
            raise exception.NotFound

    def modify_address(self, name, address, domain):

        if not self.get_entries_by_name(name, domain):
            raise exception.NotFound

        outfile = tempfile.NamedTemporaryFile('w', delete=False)
        with open(self.filename, 'r') as infile:
            for line in infile:
                entry = self.parse_line(line)
                if (entry and
                        entry['name'] == self.qualify(name, domain)):
                    outfile.write("%s   %s   %s\n" %
                        (address, self.qualify(name, domain), entry['type']))
                else:
                    outfile.write(line)
        outfile.close()
        shutil.move(outfile.name, self.filename)

    def get_entries_by_address(self, address, domain):
        entries = []
        with open(self.filename, 'r') as infile:
            for line in infile:
                entry = self.parse_line(line)
                if entry and entry['address'] == address.lower():
                    if entry['name'].endswith(domain.lower()):
                        name = entry['name'].split(".")[0]
                        if name not in entries:
                            entries.append(name)

        return entries

    def get_entries_by_name(self, name, domain):
        entries = []
        with open(self.filename, 'r') as infile:
            for line in infile:
                entry = self.parse_line(line)
                if (entry and
                        entry['name'] == self.qualify(name, domain)):
                    entries.append(entry['address'])
        return entries

    def delete_dns_file(self):
        if os.path.exists(self.filename):
            try:
                os.remove(self.filename)
            except OSError:
                pass
        if self.tempdir and os.path.exists(self.tempdir):
            try:
                shutil.rmtree(self.tempdir)
            except OSError:
                pass

    def create_domain(self, fqdomain):
        if self.get_entries_by_name(fqdomain, ''):
            raise exception.FloatingIpDNSExists(name=fqdomain, domain='')

        with open(self.filename, 'a+') as outfile:
            outfile.write("%s   %s   %s\n" %
                ('domain', fqdomain, 'domain'))

    def delete_domain(self, fqdomain):
        deleted = False
        outfile = tempfile.NamedTemporaryFile('w', delete=False)
        with open(self.filename, 'r') as infile:
            for line in infile:
                entry = self.parse_line(line)
                if (not entry or
                        entry['domain'] != fqdomain.lower()):
                    outfile.write(line)
                else:
                    LOG.info(_LI("deleted %s"), entry)
                    deleted = True
        outfile.close()
        shutil.move(outfile.name, self.filename)
        if not deleted:
            LOG.warning(_LW('Cannot delete domain |%s|'), fqdomain)
            raise exception.NotFound
