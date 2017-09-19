========================
Documentation Guidelines
========================

These are some basic guidelines for contributing to documentation in nova.

Review Guidelines
=================

Documentation-only patches differ from code patches in a few ways.

* They are often written by users / operators that aren't plugged into daily
  cycles of nova or on IRC

* Outstanding patches are far more likely to trigger merge conflict in Git than
  code patches

* There may be wide variation on points of view of what the "best" or
  "clearest" way is to say a thing

This all can lead to a large number of practical documentation improvements
stalling out because the author submitted the fix, and does not have the time
to merge conflict chase or is used to the Gerrit follow up model.

As such, documentation patches should be evaluated in the basic context of "does
this make things better than the current tree". Patches are cheap, it can
always be further enhanced in future patches.

Typo / trivial documentation only fixes should get approved with a single +2.

How users consume docs
======================

The current primary target for all documentation in nova is the web. While it
is theoretically possible to generate PDF versions of the content, the tree is
not currently well structured for that, and it's not clear there is an audience
for that.

The main nova docs tree ``doc/source`` is published per release, so there will
be copies of all of this as both the ``latest`` URL (which is master), and for
every stable release (e.g. ``pike``).

.. note::

   This raises an interesting and unexplored question about whether we want all
   of ``doc/source`` published with stable branches that will be stale and
   unimproved as we address content in ``latest``.

The ``api-ref`` and ``api-guide`` publish only from master to a single site on
`developer.openstack.org`. As such, they are effectively branchless.

Guidelines for consumable docs
==============================

* Give users context before following a link

  Most users exploring our documentation will be trying to learn about our
  software. Entry and subpages that provide links to in depth topics need to
  provide some basic context about why someone would need to know about a
  ``filter scheduler`` before following the link named filter scheduler.

  Providing these summaries helps the new consumer come up to speed more
  quickly.

* Doc moves require ``.htaccess`` redirects

  If a file is moved in a documentation source tree, we should be aware that it
  might be linked from external sources, and is now a ``404 Not Found`` error
  for real users.

  All doc moves should include an entry in ``doc/source/_extra/.htaccess`` to
  redirect from the old page to the new page.

* Images are good, please provide source

  An image is worth a 1000 words, but can go stale pretty quickly. We ideally
  want ``png`` files for display on the web, but that's a non modifiable
  format. For any new diagram contributions we should also get some kind of
  source format (``svg`` is ideal as it can be modified with open tools) along
  with ``png`` formats.

Long Term TODOs
===============

* Sort out our toctree / sidebar navigation

  During the bulk import of the install, admin, config guides we started with a
  unified toctree, which was a ton of entries, and made the navigation sidebar
  in Nova incredibly confusing. The short term fix was to just make that almost
  entirely hidden and rely on structured landing and sub pages.

  Long term it would be good to reconcile the toctree / sidebar into something
  that feels coherent.
