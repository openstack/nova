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

import errno
import os
import select

from nova import test
from nova.utils import parse_mailmap, str_dict_replace, synchronized


class ProjectTestCase(test.TestCase):
    def test_authors_up_to_date(self):
        topdir = os.path.normpath(os.path.dirname(__file__) + '/../../')
        if os.path.exists(os.path.join(topdir, '.bzr')):
            contributors = set()

            mailmap = parse_mailmap(os.path.join(topdir, '.mailmap'))

            import bzrlib.workingtree
            tree = bzrlib.workingtree.WorkingTree.open(topdir)
            tree.lock_read()
            try:
                parents = tree.get_parent_ids()
                g = tree.branch.repository.get_graph()
                for p in parents:
                    rev_ids = [r for r, _ in g.iter_ancestry(parents)
                               if r != "null:"]
                    revs = tree.branch.repository.get_revisions(rev_ids)
                    for r in revs:
                        for author in r.get_apparent_authors():
                            email = author.split(' ')[-1]
                            contributors.add(str_dict_replace(email, mailmap))

                authors_file = open(os.path.join(topdir, 'Authors'),
                                    'r').read()

                missing = set()
                for contributor in contributors:
                    if contributor == 'nova-core':
                        continue
                    if not contributor in authors_file:
                        missing.add(contributor)

                self.assertTrue(len(missing) == 0,
                                '%r not listed in Authors' % missing)
            finally:
                tree.unlock()


class LockTestCase(test.TestCase):
    def test_synchronized_wrapped_function_metadata(self):
        @synchronized('whatever')
        def foo():
            """Bar"""
            pass
        self.assertEquals(foo.__doc__, 'Bar', "Wrapped function's docstring "
                                              "got lost")
        self.assertEquals(foo.__name__, 'foo', "Wrapped function's name "
                                               "got mangled")

    def test_synchronized(self):
        rpipe1, wpipe1 = os.pipe()
        rpipe2, wpipe2 = os.pipe()

        @synchronized('testlock')
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
