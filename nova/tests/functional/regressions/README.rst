================================
 Tests for Specific Regressions
================================

When we have a bug reported by end users that we can write a full
stack reproduce on, we should. And we should keep a regression test
for that bug in our tree. It can be deleted at some future date if
needed, but largely should not be changed.

Writing Regression Tests
========================

- These should be full stack tests which inherit from
  nova.test.TestCase directly. (This is to prevent coupling with other tests).

- They should setup a full stack cloud in their setUp via fixtures

- They should each live in a file which is named test_bug_######.py

Writing Tests Before the Bug is Fixed
=====================================

TODO describe writing and landing tests before the bug is fixed as a
reproduce.
