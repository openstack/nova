..
      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

Development policies
--------------------

Out Of Tree Support
===================

While nova has many entrypoints and other places in the code that allow for
wiring in out of tree code, upstream doesn't actively make any guarantees
about these extensibility points; we don't support them, make any guarantees
about compatibility, stability, etc.

Furthermore, hooks and extension points in the code impede efforts in Nova to
support interoperability between OpenStack clouds. Therefore an effort is
being made to systematically deprecate and remove hooks, extension points, and
classloading of managers and other services.

Public Contractual APIs
========================

Although nova has many internal APIs, they are not all public contractual
APIs. Below is a link of our public contractual APIs:

* https://docs.openstack.org/api-ref/compute/

Anything not in this list is considered private, not to be used outside of
nova, and should not be considered stable.

REST APIs
==========

Follow the guidelines set in: https://wiki.openstack.org/wiki/APIChangeGuidelines

The canonical source for REST API behavior is the code *not* documentation.
Documentation is manually generated after the code by folks looking at the
code and writing up what they think it does, and it is very easy to get
this wrong.

This policy is in place to prevent us from making backwards incompatible
changes to REST APIs.

Patches and Reviews
===================

Merging a patch requires a non-trivial amount of reviewer resources.
As a patch author, you should try to offset the reviewer resources
spent on your patch by reviewing other patches. If no one does this, the review
team (cores and otherwise) become spread too thin.

For review guidelines see: :doc:`code-review`

Reverts for Retrospective Vetos
===============================

Sometimes our simple "2 +2s" approval policy will result in errors.
These errors might be a bug that was missed, or equally importantly,
it might be that other cores feel that there is a need for more
discussion on the implementation of a given piece of code.

Rather than `an enforced time-based solution`_ - for example, a patch
couldn't be merged until it has been up for review for 3 days - we have
chosen an honor-based system where core reviewers would not approve
potentially contentious patches until the proposal had been
sufficiently socialized and everyone had a chance to raise any
concerns.

Recognising that mistakes can happen, we also have a policy where
contentious patches which were quickly approved should be reverted so
that the discussion around the proposal can continue as if the patch
had never been merged in the first place. In such a situation, the
procedure is:

0. The commit to be reverted must not have been released.
1. The core team member who has a -2 worthy objection should propose a
   revert, stating the specific concerns that they feel need
   addressing.
2. Any subsequent patches depending on the to-be-reverted patch may
   need to be reverted also.
3. Other core team members should quickly approve the revert. No detailed
   debate should be needed at this point. A -2 vote on a revert is
   strongly discouraged, because it effectively blocks the right of
   cores approving the revert from -2 voting on the original patch.
4. The original patch submitter should re-submit the change, with a
   reference to the original patch and the revert.
5. The original reviewers of the patch should restore their votes and
   attempt to summarize their previous reasons for their votes.
6. The patch should not be re-approved until the concerns of the people
   proposing the revert are worked through. A mailing list discussion or
   design spec might be the best way to achieve this.

.. _`an enforced time-based solution`: https://lists.launchpad.net/openstack/msg08574.html

Metrics Gathering
=================

Nova currently has a monitor plugin to gather CPU metrics on compute nodes.
This feeds into the MetricsFilter and MetricsWeigher in the scheduler. The
CPU metrics monitor is only implemented for the libvirt compute driver.
External projects like :ceilometer-doc:`Ceilometer <>` and
:watcher-doc:`Watcher <>` consume these metrics.

Over time people have tried to add new monitor plugins for things like memory
bandwidth. There have also been attempts to expose these monitors over CLI,
the REST API, and notifications.

At the `Newton midcycle`_ it was decided that Nova does a poor job as a metrics
gathering tool, especially as it's incomplete, not tested, and there are
numerous other tools available to get this information as their primary
function.

Therefore, there is a freeze on adding new metrics monitoring plugins which
also includes exposing existing monitored metrics outside of Nova, like with
the nova-manage CLI, the REST API, or the notification bus. Long-term, metrics
gathering will likely be deprecated within Nova. Since there is not yet a clear
replacement, the deprecation is open-ended, but serves as a signal that new
deployments should not rely on the metrics that Nova gathers and should instead
focus their efforts on alternative solutions for placement.

.. _Newton midcycle: http://lists.openstack.org/pipermail/openstack-dev/2016-August/100600.html

Continuous Delivery Mentality
=============================

Nova generally tries to subscribe to a philosophy of anything we merge today
can be in production today, and people can continuously deliver Nova.

In practice this means we should not merge code that will not work until some
later change is merged, because that later change may never come, or not come
in the same release cycle, or may be substantially different from what was
originally intended. For example, if patch A uses code that is not available
until patch D later in the series.

The strategy for dealing with this in particularly long and complicated series
of changes is to start from the "bottom" with code that is no-op until it is
"turned on" at the top of the stack, generally with some feature flag, policy
rule, API microversion, etc. So in the example above, the code from patch D
should come before patch A even if nothing is using it yet, but things will
build on it. Realistically this means if you are working on a feature that
touches most of the Nova "stack", i.e. compute driver/service through to API,
you will work on the compute driver/service code first, then conductor and/or
scheduler, and finally the API. An extreme example of this can be found by
reading the `code review guide for the cross-cell resize feature`_.

Even if this philosophy is not the reality of how the vast majority of
OpenStack deployments consume Nova, it is a development philosophy to try and
avoid merging broken code.

.. _code review guide for the cross-cell resize feature: http://lists.openstack.org/pipermail/openstack-discuss/2019-May/006366.html
