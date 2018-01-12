==================================================
Efficient polling with the Changes-Since parameter
==================================================

The REST API allows you to poll for the status of certain operations by
performing a **GET** on various elements. Rather than re-downloading and
re-parsing the full status at each polling interval, your REST client
may use the *``changes-since``* parameter to check for changes since a
previous request. The *``changes-since``* time is specified as an `ISO
8601 <https://en.wikipedia.org/wiki/ISO_8601>`__ dateTime
(2011-01-24T17:08Z). The form for the timestamp is CCYY-MM-DDThh:mm:ss.
An optional time zone may be written in by appending the form ±hh:mm
which describes the timezone as an offset from UTC. When the timezone is
not specified (2011-01-24T17:08), the UTC timezone is assumed. If
nothing has changed since the *``changes-since``* time, an empty list is
returned. If data has changed, only the items changed since the
specified time are returned in the response. For example, performing a
**GET** against
https://api.servers.openstack.org/v2.1/servers?\ *``changes-since``*\ =2015-01-24T17:08Z
would list all servers that have changed since Mon, 24 Jan 2015 17:08:00
UTC.

To allow clients to keep track of changes, the changes-since filter
displays items that have been *recently* deleted. Both images and
servers contain a ``DELETED`` status that indicates that the resource
has been removed. Implementations are not required to keep track of
deleted resources indefinitely, so sending a changes since time in the
distant past may miss deletions.
