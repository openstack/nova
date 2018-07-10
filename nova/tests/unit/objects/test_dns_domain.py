# Copyright (C) 2014, Red Hat, Inc.
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

import mock

from nova.db import api as db
from nova.objects import dns_domain
from nova.tests.unit.objects import test_objects


fake_dnsd = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': 0,
    'domain': 'blah.example.com',
    'scope': 'private',
    'availability_zone': 'overthere',
    'project_id': '867530niner',
}


class _TestDNSDomain(object):
    @staticmethod
    def _compare(test, db, obj):
        for field, value in db.items():
            test.assertEqual(db[field], getattr(obj, field))

    def test_get_by_domain(self):
        with mock.patch.object(db, 'dnsdomain_get') as get:
            get.return_value = fake_dnsd
            dnsd = dns_domain.DNSDomain.get_by_domain(self.context, 'domain')
            self._compare(self, fake_dnsd, dnsd)

    def test_register_for_zone(self):
        dns_domain.DNSDomain.register_for_zone(self.context.elevated(),
                'domain', 'zone')
        dnsd = dns_domain.DNSDomain.get_by_domain(self.context, 'domain')
        self.assertEqual('domain', dnsd.domain)
        self.assertEqual('zone', dnsd.availability_zone)

    def test_register_for_project(self):
        dns_domain.DNSDomain.register_for_project(self.context.elevated(),
                'domain', 'project')
        dnsd = dns_domain.DNSDomain.get_by_domain(self.context, 'domain')
        self.assertEqual('domain', dnsd.domain)
        self.assertEqual('project', dnsd.project_id)

    def test_delete_by_domain(self):
        dns_domain.DNSDomain.register_for_zone(self.context.elevated(),
                'domain', 'zone')
        dnsd = dns_domain.DNSDomain.get_by_domain(self.context, 'domain')
        self.assertEqual('domain', dnsd.domain)
        self.assertEqual('zone', dnsd.availability_zone)

        dns_domain.DNSDomain.delete_by_domain(self.context.elevated(),
                'domain')
        dnsd = dns_domain.DNSDomain.get_by_domain(self.context, 'domain')
        self.assertIsNone(dnsd)

    def test_get_all(self):
        with mock.patch.object(db, 'dnsdomain_get_all') as get:
            get.return_value = [fake_dnsd]
            dns_domain.DNSDomainList.get_all(self.context)


class TestDNSDomainObject(test_objects._LocalTest,
                          _TestDNSDomain):
    pass


class TestRemoteDNSDomainObject(test_objects._RemoteTest,
                                _TestDNSDomain):
    pass
