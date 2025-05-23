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

Chronological PTL guide
=======================

This is just a reference guide that a PTL may use as an aid, if they choose.

New PTL
-------

* Update the nova meeting chair

  * https://github.com/openstack-infra/irc-meetings/blob/master/meetings/nova-team-meeting.yaml

* Update the team wiki

  * https://wiki.openstack.org/wiki/Nova#People

* Get acquainted with the release schedule

  * Example: https://releases.openstack.org/antelope/schedule.html

   * Also, note that we usually create a specific wiki page for each cycle like
     https://wiki.openstack.org/wiki/Nova/2023.1_Release_Schedule but it's
     preferred to use the main release schedule above.

Project Team Gathering
----------------------

* Create PTG planning etherpad, retrospective etherpad and alert about it in
  nova meeting and dev mailing list

  * Example: https://etherpad.opendev.org/p/nova-antelope-ptg

* Run sessions at the PTG

* Do a retro of the previous cycle

* Make agreement on the agenda for this release, including but not exhaustively:

  * Number of review days, for either specs or implementation
  * Define the Spec approval and Feature freeze dates
  * Modify the release schedule if needed by adding the new dates.
    As an example : https://review.opendev.org/c/openstack/releases/+/877094

* Discuss the implications of the `SLURP or non-SLURP`__ current release

.. __: https://governance.openstack.org/tc/resolutions/20220210-release-cadence-adjustment.html

* Sign up for group photo at the PTG (if applicable)


After PTG
---------

* Send PTG session summaries to the dev mailing list

* Add `RFE bugs`__ if you have action items that are simple to do but without a owner yet.

* Update IRC #openstack-nova channel topic to point to new development-planning
  etherpad.

.. __: https://bugs.launchpad.net/nova/+bugs?field.tag=rfe

A few weeks before milestone 1
------------------------------

* Plan a spec review day

* Periodically check the series goals others have proposed in the “Set series
  goals” link:

  * Example: https://blueprints.launchpad.net/nova/antelope/+setgoals

Milestone 1
-----------

* Do milestone release of nova and python-novaclient (in launchpad only, can be
  optional)

  * This is launchpad bookkeeping only. With the latest release team changes,
    projects no longer do milestone releases. See: https://releases.openstack.org/reference/release_models.html#cycle-with-milestones-legacy

  * For nova, set the launchpad milestone release as “released” with the date

* Release other libraries if there are significant enough changes since last
  release. When releasing the first version of a library for the cycle, bump
  the minor version to leave room for future stable branch releases

  * os-vif
  * placement
  * os-traits / os-resource-classes

* Release stable branches of nova

  * ``git checkout <stable branch>``

  * ``git log --no-merges <last tag>..``

    * Examine commits that will go into the release and use it to decide
      whether the release is a major, minor, or revision bump according to
      semver

  * Then, propose the release with version according to semver x.y.z

    * X - backward-incompatible changes

    * Y - features

    * Z - bug fixes

  * Use the new-release command to generate the release

    * https://releases.openstack.org/reference/using.html#using-new-release-command

Summit
------

* Prepare the project update presentation. Enlist help of others

* Prepare the on-boarding session materials. Enlist help of others

* Prepare the operator meet-and-greet session. Enlist help of others

A few weeks before milestone 2
------------------------------

* Plan a spec review day (optional)

Milestone 2
-----------

* Spec freeze (if agreed)

* Release nova and python-novaclient (if new features were merged)

* Release other libraries as needed

* Stable branch releases of nova

* For nova, set the launchpad milestone release as “released” with the date
  (can be optional)

Shortly after spec freeze
-------------------------

* Create a blueprint status etherpad to help track, especially non-priority
  blueprint work, to help things get done by Feature Freeze (FF). Example:

  * https://etherpad.opendev.org/p/nova-antelope-blueprint-status

* Create or review a patch to add the next release’s specs directory so people
  can propose specs for next release after spec freeze for current release

Non-client library release freeze
---------------------------------

* Final release for os-vif
* Final release for os-traits
* Final release for os-resource-classes

Milestone 3
-----------

* Feature freeze day

* Client library freeze, release python-novaclient and osc-placement

* Close out all blueprints, including “catch all” blueprints like mox,
  versioned notifications

* Stable branch releases of nova

* For nova, set the launchpad milestone release as “released” with the date

* Start writing the `cycle highlights
  <https://docs.openstack.org/project-team-guide/release-management.html#cycle-highlights>`__

Week following milestone 3
--------------------------

* Consider announcing the FFE (feature freeze exception process) to have people
  propose FFE requests to a special etherpad where they will be reviewed and
  possibly sponsored:

  * https://docs.openstack.org/nova/latest/contributor/process.html#non-priority-feature-freeze

  .. note::

    if there is only a short time between FF and RC1 (lately it’s been 2
    weeks), then the only likely candidates will be low-risk things that are
    almost done

* Mark the max microversion for the release in the
  :doc:`/reference/api-microversion-history`:

  * Example: https://review.opendev.org/c/openstack/nova/+/719313

A few weeks before RC
---------------------

* Make a RC1 todos etherpad and tag bugs as ``<release>-rc-potential`` and keep
  track of them, example:

  * https://etherpad.opendev.org/p/nova-antelope-rc-potential

* Go through the bug list and identify any rc-potential bugs and tag them

RC
--

* Do steps described on the release checklist wiki:

  * https://wiki.openstack.org/wiki/Nova/ReleaseChecklist

* If we want to drop backward-compat RPC code, we have to do a major RPC
  version bump and coordinate it just before the major release:

  * https://wiki.openstack.org/wiki/RpcMajorVersionUpdates

  * Example: https://review.opendev.org/541035

* “Merge latest translations" means translation patches

  * Check for translations with:

    * https://review.opendev.org/#/q/status:open+project:openstack/nova+branch:master+topic:zanata/translations

* Should NOT plan to have more than one RC if possible. RC2 should only happen
  if there was a mistake and something was missed for RC, or a new regression
  was discovered

* Do the RPC version aliases just before RC1 if no further RCs are planned.
  Else do them at RC2. In the past, we used to update all service version
  aliases (example: https://review.opendev.org/230132) but since we really
  only support compute being backlevel/old during a rolling upgrade, we only
  need to update the compute service alias, see related IRC discussion:
  http://eavesdrop.openstack.org/irclogs/%23openstack-nova/%23openstack-nova.2018-08-08.log.html#t2018-08-08T17:13:45

  * Example: https://review.opendev.org/642599

  * More detail on how version aliases work: https://docs.openstack.org/nova/latest/configuration/config.html#upgrade-levels

* Write the reno prelude for the release GA

  * Example: https://review.opendev.org/644412

* Push the cycle-highlights in marketing-friendly sentences and propose to the
  openstack/releases repo. Usually based on reno prelude but made more readable
  and friendly

  * Example: https://review.opendev.org/644697

Immediately after RC
--------------------

* Look for bot proposed changes to reno and stable/<cycle>

* Follow the post-release checklist

  * https://wiki.openstack.org/wiki/Nova/ReleaseChecklist

  * Drop old RPC compat code (if there was a RPC major version bump and if
    agreed on at the PTG)

    * Example: https://review.opendev.org/543580

  * Bump the oldest supported compute service version (if master branch is now
    on a non-SLURP version)

    * https://review.opendev.org/#/c/738482/

* Create the launchpad series for the next cycle

* Set the development focus of the project to the new cycle series

* Set the status of the new series to “active development”

* Set the last series status to “current stable branch release”

* Set the previous to last series status to “supported”

* Repeat launchpad steps ^ for python-novaclient (optional)

* Repeat launchpad steps ^ for placement

* Register milestones in launchpad for the new cycle based on the new cycle
  release schedule

* Make sure the specs directory for the next cycle gets created so people can
  start proposing new specs

* Make sure to move implemented specs from the previous release

  * Use ``tox -e move-implemented-specs <release>``

  * Also remove template from ``doc/source/specs/<release>/index.rst``

  * Also delete template file ``doc/source/specs/<release>/template.rst``

* Create new release wiki:

  * Example: https://wiki.openstack.org/wiki/Nova/2023.1_Release_Schedule

* Update the contributor guide for the new cycle

  * Example: https://review.opendev.org/#/c/754427/

Miscellaneous Notes
-------------------

How to approve a launchpad blueprint
************************************

* Set the approver as the person who +W the spec, or set to self if it’s
  specless

* Set the Direction => Approved and Definition => Approved and make sure the
  Series goal is set to the current release. If code is already proposed, set
  Implementation => Needs Code Review

* Add a comment to the Whiteboard explaining the approval, with a date
  (launchpad does not record approval dates). For example: “We discussed this
  in the team meeting and agreed to approve this for <release>. -- <nick>
  <YYYYMMDD>”

How to complete a launchpad blueprint
*************************************

* Set Implementation => Implemented. The completion date will be recorded by
  launchpad
