.. _code-review:

==========================
Code Review Guide for Nova
==========================

OpenStack has a general set of code review guidelines:
https://docs.openstack.org/infra/manual/developers.html#peer-review

What follows is a very terse set of points for reviewers to consider when
looking at nova code. These are things that are important for the
continued smooth operation of Nova, but that tend to be carried as
"tribal knowledge" instead of being written down. It is an attempt to
boil down some of those things into nearly checklist format. Further
explanation about why some of these things are important belongs
elsewhere and should be linked from here.

Upgrade-Related Concerns
========================

RPC API Versions
----------------

* If an RPC method is modified, the following needs to happen:

  * The manager-side (example: compute/manager) needs a version bump
  * The manager-side method needs to tolerate older calls as well as
    newer calls
  * Arguments can be added as long as they are optional. Arguments
    cannot be removed or changed in an incompatible way.
  * The RPC client code (example: compute/rpcapi.py) needs to be able
    to honor a pin for the older version (see
    self.client.can_send_version() calls). If we are pinned at 1.5, but
    the version requirement for a method is 1.7, we need to be able to
    formulate the call at version 1.5.
  * Methods can drop compatibility with older versions when we bump a
    major version.

* RPC methods can be deprecated by removing the client (example:
  compute/rpcapi.py) implementation. However, the manager method must
  continue to exist until the major version of the API is bumped.

Object Versions
---------------

* If a tracked attribute (i.e. listed in fields) or remotable method
  is added, or a method is changed, the object version must be
  bumped. Changes for methods follow the same rules as above for
  regular RPC methods. We have tests to try to catch these changes,
  which remind you to bump the version and then correct the
  version-hash in the tests.
* Field types cannot be changed. If absolutely required, create a
  new attribute and deprecate the old one. Ideally, support converting
  the old attribute to the new one with an obj_load_attr()
  handler. There are some exceptional cases where changing the type
  can be allowed, but care must be taken to ensure it does not affect
  the wireline API.
* New attributes should be removed from the primitive in
  obj_make_compatible() if the attribute was added after the target
  version.
* Remotable methods should not return unversioned structures wherever
  possible. They should return objects or simple values as the return
  types are not (and cannot) be checked by the hash tests.
* Remotable methods should not take complex structures as
  arguments. These cannot be verified by the hash tests, and thus are
  subject to drift. Either construct an object and pass that, or pass
  all the simple values required to make the call.
* Changes to an object as described above will cause a hash to change
  in TestObjectVersions. This is a reminder to the developer and the
  reviewer that the version needs to be bumped. There are times when
  we need to make a change to an object without bumping its version,
  but those cases are only where the hash logic detects a change that
  is not actually a compatibility issue and must be handled carefully.

Database Schema
---------------

* Changes to the database schema must generally be additive-only. This
  means you can add columns, but you can't drop or alter a column. We
  have some hacky tests to try to catch these things, but they are
  fragile. Extreme reviewer attention to non-online alterations to the
  DB schema will help us avoid disaster.
* Dropping things from the schema is a thing we need to be extremely
  careful about, making sure that the column has not been used (even
  present in one of our models) for at least a release.
* Data migrations must not be present in schema migrations. If data
  needs to be converted to another format, or moved from one place to
  another, then that must be done while the database server remains
  online. Generally, this can and should be hidden within the object
  layer so that an object can load from either the old or new
  location, and save to the new one.
* Multiple Cells v2 cells are supported started in the Pike release.
  As such, any online data migrations that move data from a cell
  database to the API database must be multi-cell aware.

REST API
=========

When making a change to the nova API, we should always follow
`the API WG guidelines <https://specs.openstack.org/openstack/api-wg/>`_
rather than going for "local" consistency.
Developers and reviewers should read all of the guidelines, but they are
very long. So here are some key points:

* `Terms <https://specs.openstack.org/openstack/api-wg/guidelines/terms.html>`_

  * ``project`` should be used in the REST API instead of ``tenant``.
  * ``server`` should be used in the REST API instead of ``instance``.
  * ``compute`` should be used in the REST API instead of ``nova``.

* `Naming Conventions <https://specs.openstack.org/openstack/api-wg/guidelines/naming.html>`_

  * URL should not include underscores; use hyphens ('-') instead.
  * The field names contained in a request/response body should
    use snake_case style, not CamelCase or Mixed_Case style.

* `HTTP Response Codes <http://specs.openstack.org/openstack/api-wg/guidelines/http/response-codes.html>`_

  * Synchronous resource creation: ``201 Created``
  * Asynchronous resource creation: ``202 Accepted``
  * Synchronous resource deletion: ``204 No Content``
  * For all other successful operations: ``200 OK``


Config Options
==============

Location
--------

The central place where all config options should reside is the ``/nova/conf/``
package. Options that are in named sections of ``nova.conf``, such as
``[serial_console]``, should be in their own module. Options that are in the
``[DEFAULT]`` section should be placed in modules that represent a natural
grouping. For example, all of the options that affect the scheduler would be
in the ``scheduler.py`` file, and all the networking options would be moved
to ``network.py``.

Implementation
--------------

A config option should be checked for:

* A short description which explains what it does. If it is a unit
  (e.g. timeouts or so) describe the unit which is used (seconds, megabyte,
  mebibyte, ...).

* A long description which explains the impact and scope. The operators should
  know the expected change in the behavior of Nova if they tweak this.

* Descriptions/Validations for the possible values.

  * If this is an option with numeric values (int, float), describe the
    edge cases (like the min value, max value, 0, -1).
  * If this is a DictOpt, describe the allowed keys.
  * If this is a StrOpt, list any possible regex validations, or provide a
    list of acceptable and/or prohibited values.

Previously used sections which explained which services consume a specific
config option and which options are related to each other got dropped
because they are too hard to maintain:
http://lists.openstack.org/pipermail/openstack-dev/2016-May/095538.html

Third Party Tests
=================

Any change that is not tested well by the Jenkins check jobs must have a
recent +1 vote from an appropriate third party test (or tests) on the latest
patchset, before a core reviewer is allowed to make a +2 vote.

Virt drivers
------------

At a minimum, we must ensure that any technology specific code has a +1
from the relevant third party test, on the latest patchset, before a +2 vote
can be applied.
Specifically, changes to nova/virt/driver/<NNNN> need a +1 vote from the
respective third party CI.
For example, if you change something in the Hyper-V virt driver, you must wait
for a +1 from the Hyper-V CI on the latest patchset, before you can give that
patch set a +2 vote.

This is important to ensure:

* We keep those drivers stable
* We don't break that third party CI

Notes
-----

Please note:

* Long term, we should ensure that any patch a third party CI is allowed to
  vote on, can be blocked from merging by that third party CI.
  But we need a lot more work to make something like that feasible, hence the
  proposed compromise.
* While its possible to break a virt driver CI system by changing code that is
  outside the virt drivers, this policy is not focusing on fixing that.
  A third party test failure should always be investigated, but the failure of
  a third party test to report in a timely manner should not block others.
* We are only talking about the testing of in-tree code. Please note the only
  public API is our REST API, see: :doc:`policies`

Should I run the experimental queue jobs on this change?
========================================================

Because we can't run all CI jobs in the check and gate pipelines, some
jobs can be executed on demand, thanks to the experimental pipeline.
To run the experimental jobs, you need to comment your Gerrit review
with "check experimental".

The experimental jobs aim to test specific features, such as LXC containers
or DVR with multiple nodes.  Also, it might be useful to run them when
we want to test backward compatibility with tools that deploy OpenStack
outside Devstack (e.g. TripleO, etc).  They can produce a non-voting
feedback of whether the system continues to work when we deprecate
or remove some options or features in Nova.

The experimental queue can also be used to test that new CI jobs are
correct before making them voting.

Database Schema
===============

* Use the ``utf8`` charset only where necessary. Some string fields, such as
  hex-stringified UUID values, MD5 fingerprints, SHA1 hashes or base64-encoded
  data, are always interpreted using ASCII encoding. A hex-stringified UUID
  value in ``latin1`` is 1/3 the size of the same field in ``utf8``, impacting
  performance without bringing any benefit. If there are no string type columns
  in the table, or the string type columns contain **only** the data described
  above, then stick with ``latin1``.

Microversion API
================

If a new microversion API is added, the following needs to happen:

* A new patch for the microversion API change in python-novaclient side
  should be submitted before the microversion change in Nova is merged.
  See :python-novaclient-doc:`Adding support for a new microversion
  <contributor/microversions>` in python-novaclient for more details.
* If the microversion changes the response schema, a new schema and test for
  the microversion must be added to Tempest. The microversion change in Nova
  should not be merged until the Tempest test is submitted and at least
  passing; it does not need to be merged yet as long as it is testing the
  Nova change via Depends-On. The Nova microversion change commit message
  should reference the Change-Id of the Tempest test for reviewers to identify
  it.

Notifications
=============

* Every new notification type shall use the new versioned notification
  infrastructure documented in :doc:`/reference/notifications`

Release Notes
=============

A release note is required on changes that have upgrade impact, security
impact, introduce a new feature, fix Critical bugs, or fix long-standing bugs
with high importance. See :doc:`releasenotes` for details on how to create a release
note, each available section and the type of content required.
