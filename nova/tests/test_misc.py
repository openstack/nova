# vim: tabstop=4 shiftwidth=4 softtabstop=4

#    Copyright 2010 OpenStack LLC
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

import commands
import errno
import glob
import os
import select

from eventlet import greenpool
from eventlet import greenthread

from nova import exception
from nova import test
from nova import utils
from nova.utils import parse_mailmap, str_dict_replace


class ExceptionTestCase(test.TestCase):
    @staticmethod
    def _raise_exc(exc):
        raise exc()

    def test_exceptions_raise(self):
        for name in dir(exception):
            exc = getattr(exception, name)
            if isinstance(exc, type):
                self.assertRaises(exc, self._raise_exc, exc)


class ProjectTestCase(test.TestCase):
    def test_authors_up_to_date(self):
        topdir = os.path.normpath(os.path.dirname(__file__) + '/../../')
        missing = set()
        contributors = set()
        mailmap = parse_mailmap(os.path.join(topdir, '.mailmap'))
        authors_file = open(os.path.join(topdir,
                                         'Authors'), 'r').read().lower()

        if os.path.exists(os.path.join(topdir, '.git')):
            for email in commands.getoutput('git log --format=%ae').split():
                if not email:
                    continue
                if "jenkins" in email and "openstack.org" in email:
                    continue
                email = '<' + email.lower() + '>'
                contributors.add(str_dict_replace(email, mailmap))
        else:
            return

        for contributor in contributors:
            if contributor == 'nova-core':
                continue
            if not contributor in authors_file:
                missing.add(contributor)

        self.assertTrue(len(missing) == 0,
                        '%r not listed in Authors' % missing)

    def test_all_new_migrations_have_downgrade(self):
        # NOTE(sirp): These migrations are old enough so that a downgrade
        # isn't a hard requirement. Would be nice to have, in these cases,
        # though, too.
        EXEMPT = """
        002_bexar.py
        003_add_label_to_networks.py
        004_add_zone_tables.py
        005_add_instance_metadata.py
        006_add_provider_data_to_volumes.py
        007_add_ipv6_to_fixed_ips.py
        009_add_instance_migrations.py
        011_live_migration.py
        012_add_ipv6_flatmanager.py
        015_add_auto_assign_to_floating_ips.py
        020_add_snapshot_id_to_volumes.py
        026_add_agent_table.py
        027_add_provider_firewall_rules.py
        """

        exempt = [e.strip() for e in EXEMPT.splitlines() if e.strip()]

        topdir = os.path.normpath(os.path.dirname(__file__) + '/../../')
        py_glob = os.path.join(topdir, "nova", "db", "sqlalchemy",
                               "migrate_repo", "versions", "*.py")
        missing_downgrade = []
        for path in glob.iglob(py_glob):
            has_upgrade = False
            has_downgrade = False
            with open(path, "r") as f:
                for line in f:
                    if 'def upgrade(' in line:
                        has_upgrade = True
                    if 'def downgrade(' in line:
                        has_downgrade = True

                if has_upgrade and not has_downgrade:
                    fname = os.path.basename(path)
                    if fname not in exempt:
                        missing_downgrade.append(fname)

        helpful_msg = (_("The following migrations are missing a downgrade:"
                         "\n\t%s") % '\n\t'.join(sorted(missing_downgrade)))
        self.assert_(not missing_downgrade, helpful_msg)


class LockTestCase(test.TestCase):
    def test_synchronized_wrapped_function_metadata(self):
        @utils.synchronized('whatever')
        def foo():
            """Bar"""
            pass
        self.assertEquals(foo.__doc__, 'Bar', "Wrapped function's docstring "
                                              "got lost")
        self.assertEquals(foo.__name__, 'foo', "Wrapped function's name "
                                               "got mangled")

    def test_synchronized_internally(self):
        """We can lock across multiple green threads"""
        saved_sem_num = len(utils._semaphores)
        seen_threads = list()

        @utils.synchronized('testlock2', external=False)
        def f(id):
            for x in range(10):
                seen_threads.append(id)
                greenthread.sleep(0)

        threads = []
        pool = greenpool.GreenPool(10)
        for i in range(10):
            threads.append(pool.spawn(f, i))

        for thread in threads:
            thread.wait()

        self.assertEquals(len(seen_threads), 100)
        # Looking at the seen threads, split it into chunks of 10, and verify
        # that the last 9 match the first in each chunk.
        for i in range(10):
            for j in range(9):
                self.assertEquals(seen_threads[i * 10],
                                  seen_threads[i * 10 + 1 + j])

        self.assertEqual(saved_sem_num, len(utils._semaphores),
                         "Semaphore leak detected")

    def test_synchronized_externally(self):
        """We can lock across multiple processes"""
        rpipe1, wpipe1 = os.pipe()
        rpipe2, wpipe2 = os.pipe()

        @utils.synchronized('testlock1', external=True)
        def f(rpipe, wpipe):
            try:
                os.write(wpipe, "foo")
            except OSError, e:
                self.assertEquals(e.errno, errno.EPIPE)
                return

            rfds, _, __ = select.select([rpipe], [], [], 1)
            self.assertEquals(len(rfds), 0, "The other process, which was"
                                            " supposed to be locked, "
                                            "wrote on its end of the "
                                            "pipe")
            os.close(rpipe)

        pid = os.fork()
        if pid > 0:
            os.close(wpipe1)
            os.close(rpipe2)

            f(rpipe1, wpipe2)
        else:
            os.close(rpipe1)
            os.close(wpipe2)

            f(rpipe2, wpipe1)
            os._exit(0)
