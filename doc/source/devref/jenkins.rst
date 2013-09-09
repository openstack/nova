Continuous Integration with Jenkins
===================================

Nova uses a `Jenkins`_ server to automate development tasks. The Jenkins
front-end is at http://jenkins.openstack.org. You must have an
account on `Launchpad`_ to be able to access the OpenStack Jenkins site.

Jenkins performs tasks such as running static code analysis, running unit
tests, and running functional tests.  For more details on the jobs being run by
Jenkins, see the code reviews on http://review.openstack.org.  Tests are run
automatically and comments are put on the reviews automatically with the
results.

You can also get a view of the jobs that are currently running from the zuul
status dashboard, http://status.openstack.org/zuul/.

.. _Jenkins: http://jenkins-ci.org
.. _Launchpad: http://launchpad.net
