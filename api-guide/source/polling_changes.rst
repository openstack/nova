=================
Efficient polling
=================

The REST API allows you to poll for the status of certain operations by
performing a **GET** on various elements. Rather than re-downloading and
re-parsing the full status at each polling interval, your REST client may
use the ``changes-since`` and/or ``changes-before`` parameters to check
for changes within a specified time.

The ``changes-since`` time or ``changes-before`` time is specified as
an `ISO 8601 <https://en.wikipedia.org/wiki/ISO_8601>`__ dateTime
(`2011-01-24T17:08Z`). The form for the timestamp is **CCYY-MM-DDThh:mm:ss**.
An optional time zone may be written in by appending the form ±hh:mm
which describes the timezone as an offset from UTC. When the timezone is
not specified (`2011-01-24T17:08`), the UTC timezone is assumed.

The following situations need to be considered:

* If nothing has changed since the ``changes-since`` time, an empty list is
  returned. If data has changed, only the items changed since the specified
  time are returned in the response. For example, performing a
  **GET** against::

    https://api.servers.openstack.org/v2.1/servers?changes-since=2015-01-24T17:08Z

  would list all servers that have changed since Mon, 24 Jan 2015 17:08:00
  UTC.

* If nothing has changed earlier than or equal to the ``changes-before``
  time, an empty list is returned. If data has changed, only the items
  changed earlier than or equal to the specified time are returned in the
  response. For example, performing a **GET** against::

    https://api.servers.openstack.org/v2.1/servers?changes-before=2015-01-24T17:08Z

  would list all servers that have changed earlier than or equal to
  Mon, 24 Jan 2015 17:08:00 UTC.

* If nothing has changed later than or equal to ``changes-since``, or
  earlier than or equal to ``changes-before``, an empty list is returned.
  If data has changed, only the items changed between ``changes-since``
  time and ``changes-before`` time are returned in the response.
  For example, performing a **GET** against::

    https://api.servers.openstack.org/v2.1/servers?changes-since=2015-01-24T17:08Z&changes-before=2015-01-25T17:08Z

  would list all servers that have changed later than or equal to Mon,
  24 Jan 2015 17:08:00 UTC, and earlier than or equal to Mon, 25 Jan 2015
  17:08:00 UTC.

Microversion change history for servers, instance actions and migrations
regarding ``changes-since`` and ``changes-before``:

* The `2.21 microversion`_ allows reading instance actions for a deleted
  server resource.
* The `2.58 microversion`_ allows filtering on ``changes-since`` when listing
  instance actions for a server.
* The `2.59 microversion`_ allows filtering on ``changes-since`` when listing
  migration records.
* The `2.66 microversion`_ adds the ``changes-before`` filter when listing
  servers, instance actions and migrations.

The ``changes-since`` filter nor the ``changes-before`` filter
change any read-deleted behavior in the os-instance-actions or
os-migrations APIs. The os-instance-actions API with the 2.21 microversion
allows retrieving instance actions for a deleted server resource.
The os-migrations API takes an optional ``instance_uuid`` filter parameter
but does not support returning deleted migration records.

To allow clients to keep track of changes, the ``changes-since`` filter
and ``changes-before`` filter displays items that have been *recently*
deleted. Servers contain a ``DELETED`` status that indicates that the
resource has been removed. Implementations are not required to keep track
of deleted resources indefinitely, so sending a ``changes-since`` time or
a ``changes-before`` time in the distant past may miss deletions.

.. _2.21 microversion: https://docs.openstack.org/nova/latest/reference/api-microversion-history.html#id19
.. _2.58 microversion: https://docs.openstack.org/nova/latest/reference/api-microversion-history.html#id53
.. _2.59 microversion: https://docs.openstack.org/nova/latest/reference/api-microversion-history.html#id54
.. _2.66 microversion: https://docs.openstack.org/nova/latest/reference/api-microversion-history.html#id59
