===========================
 Contributor Documentation
===========================

Contributing to nova gives you the power to help add features, fix bugs,
enhance documentation, and increase testing. Contributions of any type are
valuable, and part of what keeps the project going. Here are a list of
resources to get your started.

Getting Started
===============

* :doc:`/contributor/how-to-get-involved`: Overview of engaging in the project
* :doc:`/contributor/development-environment`: Get your computer setup to
  contribute

Nova Process
============

The nova community is a large community. We have lots of users, and they all
have a lot of expectations around upgrade and backwards compatibility.  For
example, having a good stable API, with discoverable versions and capabilities
is important for maintaining the strong ecosystem around nova.

Our process is always evolving, just as nova and the community around nova
evolves over time. If there are things that seem strange, or you have ideas on
how to improve things, please bring them forward on IRC or the openstack-dev
mailing list, so we continue to improve how the nova community operates.

This section looks at the processes and why. The main aim behind all the
process is to aid communication between all members of the nova community,
while keeping users happy and keeping developers productive.

* :doc:`/contributor/project-scope`: The focus is on features and bug fixes
  that make nova work better within this scope

* :doc:`/contributor/policies`: General guidelines about what's supported

* :doc:`/contributor/process`: The processes we follow around feature and bug
  submission, including how the release calendar works, and the freezes we go
  under

* :doc:`/contributor/blueprints`: An overview of our tracking artifacts.

Reviewing
=========

* :doc:`/contributor/releasenotes`: When we need a release note for a
  contribution.

* :doc:`/contributor/code-review`: Important cheat sheet for what's important
  when doing code review in Nova, especially some things that are hard to test
  for, but need human eyes.

* :doc:`/reference/i18n`: What we require for i18n in patches

* :doc:`/contributor/documentation`: Guidelines for handling documentation
  contributions


Testing
=======

Because Python is a dynamic language, code that is not tested might not even
be Python code. All new code needs to be validated somehow.

* :doc:`/contributor/testing`: An overview of our test taxonomy and the kinds
  of testing we do and expect.

* **Testing Guides**: There are also specific testing guides for features that
  are hard to test in our gate.

  * :doc:`/contributor/testing/libvirt-numa`

  * :doc:`/contributor/testing/serial-console`

  * :doc:`/contributor/testing/zero-downtime-upgrade`

The Nova API
============

Because we have many consumers of our API, we're extremely careful about
changes done to the API, as the impact can be very wide.

* :doc:`/contributor/api`: How the code is structured inside the API layer

* :doc:`/contributor/api-2`: (needs update)

* :doc:`/contributor/microversions`: How the API is (micro)versioned and what
  you need to do when adding an API exposed feature that needs a new
  microversion.

Nova Major Subsystems
=====================

Major subsystems in nova have different needs; some of those are documented
here. If you are contributing to one of these please read the subsystem guide
before diving in.

* :doc:`/contributor/placement`

* :doc:`/user/conductor`
