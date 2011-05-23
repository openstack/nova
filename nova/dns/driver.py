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
Dns Driver base class that all Schedulers should inherit from
"""


from nova.exception import NotFound


class DnsDriver(object):
    """The base class that all Dns drivers should inherit from."""

    def __init__(self):
        pass

    def create_entry(self, entry):
        """Creates the entry in the driver at the given dns zone."""
        pass

    def delete_entry(self, name, type, dns_zone=None):
        """Deletes an entry with the given name and type from a dns zone."""
        pass

    def get_entries_by_content(self, content, dns_zone=None):
        """Retrieves all entries in a dns_zone with a matching content field."""
        pass

    def get_entries_by_name(self, name, dns_zone=None):
        """Retrieves all entries in a dns zone with the given name field."""
        pass

    def get_dns_zones(self, name=None):
        """Returns all dns zones (optionally filtered by the name argument."""
        pass

    def modify_content(self, name, content, dns_zone):
        #TODO(tim.simpson) I've found no use for this in RS impl of DNS w/
        #                  instances. Check to see its really needed.
        pass

    def rename_entry(self, content, name, dns_zone):
        #TODO(tim.simpson) I've found no use for this in RS impl of DNS w/
        #                  instances. Check to see its really needed.
        pass


class DnsInstanceEntryFactory(object):
    """Defines how instance DNS entries are created for instances.

    By default, the DNS entry returns None meaning instances do not get entries
    associated with them. Override the create_entry method to change this
    behavior.

    """

    def create_entry(self, instance):
        return None


class DnsSimpleInstanceEntryFactory(object):
    """Creates a CNAME with the name being the instance name."""

    def create_entry(self, instance):
        return DnsEntry(name=instance.name, content=None, type="CNAME")


class DnsEntry(object):
    """Simple representation of a DNS record."""

    def __init__(self, name, content, type, ttl=None, priority=None,
                 dns_zone=None):
        self.content = content
        self.name = name
        self.type = type
        self.priority = priority
        self.dns_zone = dns_zone
        self.ttl = ttl

    def __str__(self):
        return "{ name:%s, content:%s, type:%s, zone:%s }" % \
               (self.name, self.content, self.type, self.dns_zone)


class DnsEntryNotFound(NotFound):
    """Raised when a driver cannot find a DnsEntry."""
    pass


class DnsZone(object):
    """Represents a DNS Zone.

    For some APIs it is inefficient to simply represent a zone as a string
    because this would necessitate a look up on every call.  So this opaque
    object can contain additional data needed by the DNS driver.  The only
    constant is it must contain the domain name of the zone.

    """

    @property
    def name(self):
        return ""

    def __str__(self):
        return self.name
