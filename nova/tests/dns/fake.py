# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2011 Openstack, LLC.
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
Fakes a DNS driver to make testing easier.
"""


from nova.dns.driver import DnsEntryNotFound
from nova.dns.driver import DnsZone


class FakeDnsDriver(object):
    """Fakes a DnsDriver.  Useful for unit testing."""

    def __init__(self, default_dns_zone=None):
        self.default_zone = default_dns_zone or DnsZone()
        self.zones = FakeZoneHolder()

    def create_entry(self, entry):
        #name, content, type, dns_zone, priority=None
        if not entry.dns_zone:
            entry.dns_zone = self.default_zone
        print("Creating entry for " + str(entry))
        self.zones.add_entry(entry)

    def delete_entry(self, name, type, dns_zone=None):
        dns_zone = dns_zone or self.default_zone
        if not self.zones.contains_entry(dns_zone=dns_zone, name=name):
            raise DnsEntryNotFound("No entry found in dns zone %s for name %s."
                                   % (dns_zone, name))
        self.zones.delete_entry(name, dns_zone)

    def get_entries_by_content(self, content, dns_zone=None):
        dns_zone = dns_zone or self.default_zone
        zone = self.zones.get_zone(dns_zone)
        return (entry for entry in zone if entry.content == content)

    def get_entries_by_name(self, name, dns_zone=None):
        dns_zone = dns_zone or self.default_zone
        zone = self.zones.get_zone(dns_zone)
        return (entry for entry in zone if entry.name == name)

    def get_dns_zones(self, name=None):
        return self.zones.zone_names

    def modify_content(self, name, content, dns_zone):
        dns_zone = dns_zone or self.default_zone
        entry = self.get_entries_by_name(name, dns_zone)
        entry.content = content

    def rename_entry(self, content, name, dns_zone):
        dns_zone = dns_zone or self.default_zone
        entry = self.get_entries_by_content(content, dns_zone)
        entry.name = name


class FakeZoneHolder(object):

    def __init__(self):
        self.zones = {}

    def add_entry(self, entry):
        zone = self.get_zone(entry.dns_zone)
        if self.contains_entry(entry.dns_zone, entry.name):
            raise RuntimeError("A entry with name %s already found in zone %s."
                                % (entry.name, entry.dns_zone))
        zone.append(entry)

    def contains_entry(self, dns_zone, name):
        return self.find_entry(dns_zone, name) != None

    def delete_entry(self, name, dns_zone):
        zone = self.get_zone(dns_zone)
        self.zones[dns_zone.name] = [entry for entry in zone
                                     if entry.name != name]

    def find_entry(self, dns_zone, name):
        zone = self.get_zone(dns_zone)
        for entry in zone:
            if entry.name == name:
                return entry
        return None

    def get_zone(self, dns_zone):
        if not dns_zone.name in self.zones:
            self.zones[dns_zone.name] = []
        return self.zones[dns_zone.name]

    @property
    def zone_names(self):
        return self.zones.keys()
