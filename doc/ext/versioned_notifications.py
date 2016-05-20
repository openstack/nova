# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#   http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""
This provides a sphinx extension able to list the implemented versioned
notifications into the developer documentation.

It is used via a single directive in the .rst file

  .. versioned_notifications::

"""

from sphinx.util.compat import Directive
from docutils import nodes

from nova.objects import base
from nova.objects import notification


def full_name(cls):
    return cls.__module__ + '.' + cls.__name__


class VersionedNotificationDirective(Directive):

    LINK_PREFIX = 'https://git.openstack.org/cgit/openstack/nova/plain/'
    SAMPLE_ROOT = 'doc/notification_samples/'

    def run(self):
        notifications = self._collect_notifications()
        return self._build_markup(notifications)

    def _collect_notifications(self):
        notifications = []
        ovos = base.NovaObjectRegistry.obj_classes()
        for name, cls in ovos.items():
            cls = cls[0]
            if (issubclass(cls, notification.NotificationBase) and
                    cls != notification.NotificationBase):

                payload_name = cls.fields['payload'].objname
                payload_cls = ovos[payload_name][0]

                notifications.append((full_name(cls), full_name(payload_cls),
                                      cls.sample))
        return notifications

    def _build_markup(self, notifications):
        content = []
        cols = ['Notification class', 'Payload class', 'Sample file link']
        table = nodes.table()
        content.append(table)
        group = nodes.tgroup(cols=len(cols))
        table.append(group)

        head = nodes.thead()
        group.append(head)

        for i in range(len(cols)):
            group.append(nodes.colspec(colwidth=1))

        body = nodes.tbody()
        group.append(body)

        # fill the table header
        row = nodes.row()
        body.append(row)
        for col_name in cols:
            col = nodes.entry()
            row.append(col)
            text = nodes.strong(text=col_name)
            col.append(text)

        # fill the table content, one notification per row
        for name, payload, sample in notifications:
            row = nodes.row()
            body.append(row)
            col = nodes.entry()
            row.append(col)
            text = nodes.literal(text=name)
            col.append(text)

            col = nodes.entry()
            row.append(col)
            text = nodes.literal(text=payload)
            col.append(text)

            col = nodes.entry()
            row.append(col)
            ref = nodes.reference(refuri=self.LINK_PREFIX +
                                  self.SAMPLE_ROOT + sample)
            txt = nodes.inline()
            col.append(txt)
            txt.append(ref)
            ref.append(nodes.literal(text=sample))

        return content


def setup(app):
    app.add_directive('versioned_notifications',
                      VersionedNotificationDirective)
