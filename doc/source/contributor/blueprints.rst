==================================
Blueprints, Specs and Priorities
==================================

Like most OpenStack projects, Nova uses `blueprints`_ and specifications (specs) to track new
features, but not all blueprints require a spec. This document covers when a spec is needed.


.. note:: Nova's specs live at: `specs.openstack.org`_


.. _`blueprints`: http://docs.openstack.org/infra/manual/developers.html#working-on-specifications-and-blueprints
.. _`specs.openstack.org`: http://specs.openstack.org/openstack/nova-specs/


Specs
=====

A spec is needed for any feature that requires a design discussion. All
features need a blueprint but not all blueprints require a spec.

If a new feature is straightforward enough that it doesn't need any design
discussion, then no spec is required. In order to provide the sort of
documentation that would otherwise be provided via a spec, the commit
message should include a ``DocImpact`` flag and a thorough description
of the feature from a user/operator perspective.

Guidelines for when a feature doesn't need a spec.

* Is the feature a single self contained change?

  * If the feature touches code all over the place, it probably should have
    a design discussion.
  * If the feature is big enough that it needs more than one commit, it
    probably should have a design discussion.
* Not an API change.

  * API changes always require a design discussion.

When a blueprint does not require a spec it still needs to be
approved before the code which implements the blueprint is merged.
Specless blueprints are discussed and potentially approved during
the `Open Discussion` portion of the weekly `nova IRC meeting`_. See
`trivial specifications`_ for more details.

Project Priorities
===================

* Pick several project priority themes, in the form of use cases, to help us
  prioritize work

  * Generate list of improvement blueprints based on the themes
  * Produce rough draft of list going into summit and finalize the list at
    the summit
  * Publish list of project priorities and look for volunteers to work on them
* Update spec template to include

  * Specific use cases
  * State if the spec is project priority or not
* Keep an up to date list of project priority blueprints that need code review in an etherpad.

* Consumers of project priority and project priority blueprint lists:

  * Reviewers looking for direction of where to spend their blueprint review
    time.  If a large subset of nova-core doesn't use the project
    priorities it means the core team is not aligned properly and should
    revisit the list of project priorities
  * The blueprint approval team, to help find the right balance of blueprints
  * Contributors looking for something to work on
  * People looking for what they can expect in the next release

.. _nova IRC meeting: http://eavesdrop.openstack.org/#Nova_Team_Meeting
.. _trivial specifications: https://specs.openstack.org/openstack/nova-specs/readme.html#trivial-specifications
