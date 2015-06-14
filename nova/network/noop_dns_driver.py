# Copyright 2012 Red Hat, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


from nova.network import dns_driver


class NoopDNSDriver(dns_driver.DNSDriver):
    """No-op DNS manager. Does nothing."""

    def __init__(self):
        pass

    def get_domains(self):
        return []

    def create_entry(self, _name, _address, _type, _domain):
        pass

    def delete_entry(self, _name, _domain):
        pass

    def modify_address(self, _name, _address, _domain):
        pass

    def get_entries_by_address(self, _address, _domain):
        return []

    def get_entries_by_name(self, _name, _domain):
        return []

    def create_domain(self, _fqdomain):
        pass

    def delete_domain(self, _fqdomain):
        pass
