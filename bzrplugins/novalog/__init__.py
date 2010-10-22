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

"""Log format for Nova's changelog."""

import bzrlib.log
from bzrlib.osutils import format_date


class NovaLogFormat(bzrlib.log.GnuChangelogLogFormatter):
    """This is mostly stolen from bzrlib.log.GnuChangelogLogFormatter
    The difference is that it logs the author rather than the committer
    which for Nova always is Tarmac."""

    preferred_levels = 1

    def log_revision(self, revision):
        """Log a revision, either merged or not."""
        to_file = self.to_file

        date_str = format_date(revision.rev.timestamp,
                               revision.rev.timezone or 0,
                               self.show_timezone,
                               date_fmt='%Y-%m-%d',
                               show_offset=False)

        authors = revision.rev.get_apparent_authors()
        to_file.write('%s  %s\n\n' % (date_str, ", ".join(authors)))

        if revision.delta is not None and revision.delta.has_changed():
            for c in revision.delta.added + revision.delta.removed + \
                     revision.delta.modified:
                path, = c[:1]
                to_file.write('\t* %s:\n' % (path,))
            for c in revision.delta.renamed:
                oldpath, newpath = c[:2]
                # For renamed files, show both the old and the new path
                to_file.write('\t* %s:\n\t* %s:\n' % (oldpath, newpath))
            to_file.write('\n')

        if not revision.rev.message:
            to_file.write('\tNo commit message\n')
        else:
            message = revision.rev.message.rstrip('\r\n')
            for l in message.split('\n'):
                to_file.write('\t%s\n' % (l.lstrip(),))
            to_file.write('\n')

bzrlib.log.register_formatter('novalog', NovaLogFormat)
