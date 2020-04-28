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

.. _getting_involved:

=====================================
How to get (more) involved with Nova
=====================================

So you want to get more involved with Nova? Or you are new to Nova and
wondering where to start?

We are working on building easy ways for you to get help and ideas on
how to learn more about Nova and how the Nova community works.

Any questions, please ask! If you are unsure who to ask, then please
contact the `PTL`__.

__ `Nova People`_

How do I get started?
=====================

There are quite a few global docs on this:

- https://docs.openstack.org/contributors/
- https://www.openstack.org/community/
- https://www.openstack.org/assets/welcome-guide/OpenStackWelcomeGuide.pdf
- https://wiki.openstack.org/wiki/How_To_Contribute

There is more general info, non Nova specific info here:

- https://wiki.openstack.org/wiki/Mentoring
- https://docs.openstack.org/upstream-training/

What should I work on?
~~~~~~~~~~~~~~~~~~~~~~

So you are starting out your Nova journey, where is a good place to
start?

If you'd like to learn how Nova works before changing anything (good idea!), we
recommend looking for reviews with -1s and -2s and seeing why they got
downvoted. There is also the :ref:`code-review`. Once you have some
understanding, start reviewing patches. It's OK to ask people to explain things
you don't understand. It's also OK to see some potential problems but put a +0.

Once you're ready to write code, take a look at some of the work already marked
as low-hanging fruit:

* https://bugs.launchpad.net/nova/+bugs?field.tag=low-hanging-fruit

How do I get my feature in?
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The best way of getting your feature in is... well it depends.

First concentrate on solving your problem and/or use case, don't fixate
on getting the code you have working merged. It's likely things will need
significant re-work after you discuss how your needs match up with all
the existing ways Nova is currently being used. The good news, is this
process should leave you with a feature that's more flexible and doesn't
lock you into your current way of thinking.

A key part of getting code merged, is helping with reviewing other
people's code. Great reviews of others code will help free up more core
reviewer time to look at your own patches. In addition, you will
understand how the review is thinking when they review your code.

Also, work out if any on going efforts are blocking your feature and
helping out speeding those up. The spec review process should help with
this effort.

For more details on our process, please see: :ref:`process`.

What is expected of a good contributor?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

TODO - need more info on this

Top Tips for working with the Nova community
============================================

Here are some top tips around engaging with the Nova community:

-  IRC

   -  we talk a lot in #openstack-nova
   -  do ask us questions in there, and we will try to help you
   -  not sure about asking questions? feel free to listen in around
      other people's questions
   -  we recommend you setup an IRC bouncer:
      https://docs.openstack.org/contributors/common/irc.html

-  Email

   -  Use the [nova] tag in the mailing lists
   -  Filtering on [nova] and [all] can help tame the list

-  Be Open

   -  i.e. don't review your teams code in private, do it publicly in
      gerrit
   -  i.e. be ready to talk about openly about problems you are having,
      not "theoretical" issues
   -  that way you can start to gain the trust of the wider community

-  Got a problem? Please ask!

   -  Please raise any problems and ask questions early
   -  we want to help you before you are frustrated or annoyed
   -  unsure who to ask? Just ask in IRC, or check out the list of `Nova
      people`_.

-  Talk about problems first, then solutions

   -  Nova is a big project. At first, it can be hard to see the big
      picture
   -  Don't think about "merging your patch", instead think about
      "solving your problem"
   -  conversations are more productive that way

-  It's not the decision that's important, it's the reason behind it that's
   important

   -  Don't like the way the community is going?
   -  Please ask why we were going that way, and please engage with the
      debate
   -  If you don't, we are unable to learn from what you have to offer

-  No one will decide, this is stuck, who can help me?

   -  it's rare, but it happens
   -  it's the `Nova PTL`__'s job to help you
   -  ...but if you don't ask, it's hard for them to help you

__ `Nova People`_

Process
=======

It can feel like you are faced with a wall of process. We are a big
community, to make sure the right communication happens, we do use a
minimal amount of process.

If you find something that doesn't make sense, please:

-  ask questions to find out \*why\* it happens
-  if you know of a better way to do it, please speak up
-  one "better way" might be to remove the process if it no longer helps

To learn more about Nova's process, please read :ref:`process`.

Why bother with any process?
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Why is it worth creating a bug or blueprint to track your code review?
This may seem like silly process, but there is usually a good reason
behind it.

We have lots of code to review, and we have tools to try and get to
really important code reviews first. If yours is really important, but
not picked up by our tools, it's possible you just get lost in the bottom
of a big queue.

If you have a bug fix, you have done loads of work to identify the
issue, and test out your fix, and submit it. By adding a bug report, you
are making it easier for other folks who hit the same problem to find
your work, possibly saving them the hours of pain you went through. With
any luck that gives all those people the time to fix different bugs, all
that might have affected you, if you had not given them the time go fix
it.

It's similar with blueprints. You have worked out how to scratch your
itch, lets tell others about that great new feature you have added, so
they can use that. Also, it stops someone with a similar idea going
through all the pain of creating a feature only to find you already have
that feature ready and up for review, or merged into the latest release.

Hopefully this gives you an idea why we have applied a small layer of
process to what we are doing. Having said all this, we need to unlearn
old habits to move forward, there may be better ways to do things, and
we are open to trying them. Please help be part of the solution.

.. _why_plus1:

Why do code reviews if I am not in nova-core?
=============================================

Code reviews are the life blood of the Nova developer community.

There is a good discussion on how you do good reviews, and how anyone
can be a reviewer:
http://docs.openstack.org/infra/manual/developers.html#peer-review

In the draft process guide, I discuss how doing reviews can help get
your code merged faster: :ref:`process`.

Lets look at some of the top reasons why participating with code reviews
really helps you:

-  Doing more reviews, and seeing what other reviewers notice, will help
   you better understand what is expected of code that gets merged into
   master.
-  Having more non-core people do great reviews, leaves less review work
   for the core reviewers to do, so we are able get more code merged.
-  Empathy is one of the keys to a happy community. If you are used to
   doing code reviews, you will better understand the comments you get
   when people review your code. As you do more code reviews, and see
   what others notice, you will get a better idea of what people are
   looking for when then apply a +2 to your code.
-  If you do quality reviews, you'll be noticed and it's more likely
   you'll get reciprocal eyes on your reviews.

What are the most useful types of code review comments? Well here are a
few to the top ones:

-  Fundamental flaws are the biggest thing to spot. Does the patch break
   a whole set of existing users, or an existing feature?
-  Consistency of behaviour is really important. Does this bit of code
   do things differently to where similar things happen else where in
   Nova?
-  Is the code easy to maintain, well tested and easy to read? Code is
   read order of magnitude times more than it is written, so optimise
   for the reader of the code, not the writer.
-  TODO - what others should go here?

Let's look at some problems people hit when starting out doing code
reviews:

-  My +1 doesn't mean anything, why should I bother?

   -  So your +1 really does help. Some really useful -1 votes that lead
      to a +1 vote helps get code into a position

-  When to use -1 vs 0 vs +1

   -  Please see the guidelines here:
      http://docs.openstack.org/infra/manual/developers.html#peer-review

-  I have already reviewed this code internally, no point in adding a +1
   externally?

   -  Please talk to your company about doing all code reviews in the
      public, that is a much better way to get involved. showing how the
      code has evolved upstream, is much better than trying to 'perfect'
      code internally, before uploading for public review. You can use
      Draft mode, and mark things as WIP if you prefer, but please do
      the reviews upstream.

-  Where do I start? What should I review?

   -  There are various tools, but a good place to start is:
      https://etherpad.openstack.org/p/nova-runways-victoria
   -  Depending on the time in the cycle, it's worth looking at
      NeedsCodeReview blueprints:
      https://blueprints.launchpad.net/nova/
   -  Custom Gerrit review dashboards often provide a more manageable view of
      the outstanding reviews, and help focus your efforts:

      -  Nova Review Inbox:
         https://goo.gl/1vTS0Z
      -  Small Bug Fixes:
         http://ow.ly/WAw1J

   -  Maybe take a look at things you want to see merged, bug fixes and
      features, or little code fixes
   -  Look for things that have been waiting a long time for a review:
      https://review.opendev.org/#/q/project:openstack/nova+status:open+age:2weeks
   -  If you get through the above lists, try other tools, such as:
      http://status.openstack.org/reviews

How to do great code reviews?
=============================

http://docs.openstack.org/infra/manual/developers.html#peer-review

For more tips, please see: `Why do code reviews if I am not in nova-core?`_

How do I become nova-core?
==========================

You don't have to be nova-core to be a valued member of the Nova
community. There are many, many ways you can help. Every quality review
that helps someone get their patch closer to being ready to merge helps
everyone get their code merged faster.

The first step to becoming nova-core is learning how to be an active
member of the Nova community, including learning how to do great code
reviews. For more details see:
https://wiki.openstack.org/wiki/Nova/CoreTeam#Membership_Expectations

If you feel like you have the time to commit to all the nova-core
membership expectations, reach out to the Nova PTL who will be
able to find you an existing member of nova-core to help mentor you. If
all goes well, and you seem like a good candidate, your mentor will
contact the rest of the nova-core team to ask them to start looking at
your reviews, so they are able to vote for you, if you get nominated for
join nova-core.

We encourage all mentoring, where possible, to occur on #openstack-nova
so everyone can learn and benefit from your discussions.

The above mentoring is available to every one who wants to learn how to
better code reviews, even if you don't ever want to commit to becoming
nova-core. If you already have a mentor, that's great, the process is
only there for folks who are still trying to find a mentor. Being
admitted to the mentoring program no way guarantees you will become a
member of nova-core eventually, it's here to help you improve, and help
you have the sort of involvement and conversations that can lead to
becoming a member of nova-core.

How to do great nova-spec reviews?
==================================

https://specs.openstack.org/openstack/nova-specs/specs/victoria/template.html

:doc:`/contributor/blueprints`.

Spec reviews are always a step ahead of the normal code reviews. Follow
the above links for some great information on specs/reviews.

The following could be some important tips:

1. The specs are published as html documents. Ensure that the author has
a proper render of the same via the .rst file.

2. More often than not, it's important to know that there are no
overlaps across multiple specs.

3. Ensure that a proper dependency of the spec is identified. For
example - a user desired feature that requires a proper base enablement
should be a dependent spec.

4. Ask for clarity on changes that appear ambiguous to you.

5. Every release nova gets a huge set of spec proposals and that's a
huge task for the limited set of nova cores to complete. Helping the
cores with additional reviews is always a great thing.

How to do great bug triage?
===========================

https://wiki.openstack.org/wiki/Nova/BugTriage

Sylvain Bauza and Stephen Finucane gave a nice `presentation`_ on this topic
at the Queens summit in Sydney.

.. _presentation: https://www.openstack.org/videos/sydney-2017/upstream-bug-triage-the-hidden-gem

How to step up into a project leadership role?
==============================================

There are many ways to help lead the Nova project:

* Mentoring efforts, and getting started tips:
  https://wiki.openstack.org/wiki/Nova/Mentoring
* Info on process, with a focus on how you can go from an idea
  to getting code merged Nova: :ref:`process`
* Consider leading an existing `Nova subteam`_ or forming a new one.
* Consider becoming a `Bug tag owner`_.
* Contact the PTL about becoming a Czar `Nova People`_.

.. _`Nova people`: https://wiki.openstack.org/wiki/Nova#People
.. _`Nova subteam`: https://wiki.openstack.org/wiki/Nova#Nova_subteams
.. _`Bug tag owner`: https://wiki.openstack.org/wiki/Nova/BugTriage#Tag_Owner_List
