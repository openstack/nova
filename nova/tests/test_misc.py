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

import os

from nova import test
from nova.utils import parse_mailmap, str_dict_replace


class ProjectTestCase(test.TestCase):
    def test_authors_up_to_date(self):
        if os.path.exists('.bzr'):
            contributors = set()

            mailmap = parse_mailmap('.mailmap')

            import bzrlib.workingtree
            tree = bzrlib.workingtree.WorkingTree.open('.')
            tree.lock_read()
            try:
                parents = tree.get_parent_ids()
                g = tree.branch.repository.get_graph()
                for p in parents[1:]:
                    rev_ids = [r for r, _ in g.iter_ancestry(parents)
                               if r != "null:"]
                    revs = tree.branch.repository.get_revisions(rev_ids)
                    for r in revs:
                        for author in r.get_apparent_authors():
                            email = author.split(' ')[-1]
                            contributors.add(str_dict_replace(email, mailmap))

                authors_file = open('Authors', 'r').read()

                missing = set()
                for contributor in contributors:
                    if contributor == 'nova-core':
                        pass
                    if not contributor in authors_file:
                        missing.add(contributor)

                self.assertTrue(len(missing) == 0,
                                '%r not listed in Authors' % missing)
            finally:
                tree.unlock()
