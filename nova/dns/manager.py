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
Dns manager.
"""

from nova import flags
from nova import log as logging
from nova import utils
from nova.manager import Manager

FLAGS = flags.FLAGS
flags.DEFINE_string('dns_driver', 'nova.dns.driver.DnsDriver',
                    'Driver to use for DNS work')
flags.DEFINE_string('dns_instance_entry_factory',
                    'nova.dns.driver.DnsInstanceEntryFactory',
                    'Method used to create entries for instances')

LOG = logging.getLogger('nova.dns.manager')

class DnsManager(Manager):
    """Handles associating DNS to and from IPs."""

    def __init__(self, dns_driver=None, dns_instance_entry_factory=None,
                 *args, **kwargs):
        if not dns_driver:
            dns_driver = FLAGS.dns_driver
        self.driver = utils.import_object(dns_driver)
        if not dns_instance_entry_factory:
            dns_instance_entry_factory = FLAGS.dns_instance_entry_factory
        self.entry_factory = utils.import_object(dns_instance_entry_factory)
        super(DnsManager, self).__init__(*args, **kwargs)

    def create_instance_entry(self, instance, content):
        """Connects a new instance with a DNS entry.

        :param instance: The compute instance to associate.
        :param content: The IP content attached to the instance.

        """
        entry = self.entry_factory.create_entry(instance)
        LOG.debug("Creating entry address %s." % str(entry))
        print("create instance entry " + str(entry))
        if entry:
            entry.content = content
            self.driver.create_entry(entry)

    def delete_instance_entry(self, instance, content):
        """Removes a DNS entry associated to an instance."""
        entry = self.entry_factory.create_entry(instance)
        LOG.debug("Deleting instance entry with %s" % str(entry))
        if entry:
            entry.content = content
            self.driver.delete_entry(entry.name, entry.type)
