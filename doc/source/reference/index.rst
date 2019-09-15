================================
 Technical Reference Deep Dives
================================

The nova project is large, and there are lots of complicated parts in it where
it helps to have an overview to understand how the internals of a particular
part work.

.. _reference-internals:

Internals
=========

The following is a dive into some of the internals in nova.

* :doc:`/reference/rpc`: How nova uses AMQP as an RPC transport
* :doc:`/reference/scheduling`: The workflow through the scheduling process
* :doc:`/reference/scheduler-hints-vs-flavor-extra-specs`: The similarities
  and differences between flavor extra specs and scheduler hints.
* :doc:`/reference/live-migration`: The live migration flow
* :doc:`/reference/services`: Module descriptions for some of the key modules
  used in starting / running services
* :doc:`/reference/vm-states`: Cheat sheet for understanding the life cycle of
  compute instances
* :doc:`/reference/threading`: The concurrency model used in nova, which is
  based on eventlet, and may not be familiar to everyone.
* :doc:`/reference/notifications`: How the notifications subsystem works in
  nova, and considerations when adding notifications.
* :doc:`/reference/update-provider-tree`: A detailed explanation of the
  ``ComputeDriver.update_provider_tree`` method.
* :doc:`/reference/upgrade-checks`: A guide to writing automated upgrade
  checks.
* :doc:`/reference/conductor`

.. todo:: Need something about versioned objects and how they fit in with
          conductor as an object backporter during upgrades.

* :doc:`/reference/isolate-aggregates`: Describes how the placement filter
  works in nova to isolate groups of hosts.

Debugging
=========

* :doc:`/reference/gmr`: Inspired by Amiga, a way to trigger a very
  comprehensive dump of a running service for deep debugging.

Forward Looking Plans
=====================

The following section includes documents that describe the overall plan behind
groups of nova-specs. Most of these cover items relating to the evolution of
various parts of nova's architecture. Once the work is complete,
these documents will move into the "Internals" section.

If you want to get involved in shaping the future of nova's architecture,
these are a great place to start reading up on the current plans.

* :doc:`/user/cells`: How cells v2 is evolving
* :doc:`/reference/policy-enforcement`: How we want policy checks on API actions
  to work in the future
* :doc:`/reference/stable-api`: What stable api means to nova
* :doc:`/reference/scheduler-evolution`: Motivation behind the scheduler /
  placement evolution
