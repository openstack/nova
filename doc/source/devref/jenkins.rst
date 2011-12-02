Continuous Integration with Jenkins
===================================

Nova uses a `Jenkins`_ server to automate development tasks. The Jenkins
front-end is at http://jenkins.openstack.org. You must have an
account on `Launchpad`_ to be able to access the OpenStack Jenkins site.

Jenkins performs tasks such as:

`gate-nova-unittests`_
    Run unit tests on proposed code changes that have been reviewed.

`gate-nova-pep8`_
    Run PEP8 checks on proposed code changes that have been reviewed.

`gate-nova-merge`_
    Merge reviewed code into the git repository.

`nova-coverage`_
    Calculate test coverage metrics.

`nova-docs`_
    Build this documentation and push it to http://nova.openstack.org.

`nova-pylint`_
    Run `pylint <http://www.logilab.org/project/pylint>`_ on the nova code and
    report violations.

`nova-tarball`_
    Do ``python setup.py sdist`` to create a tarball of the nova code and upload
    it to http://nova.openstack.org/tarballs

.. _Jenkins: http://jenkins-ci.org
.. _Launchpad: http://launchpad.net
.. _gate-nova-merge: https://jenkins.openstack.org/view/Nova/job/gate-nova-merge
.. _gate-nova-pep8: https://jenkins.openstack.org/view/Nova/job/gate-nova-pep8
.. _gate-nova-unittests: https://jenkins.openstack.org/view/Nova/job/gate-nova-unittests
.. _nova-coverage: https://jenkins.openstack.org/view/Nova/job/nova-coverage
.. _nova-docs: https://jenkins.openstack.org/view/Nova/job/nova-docs
.. _nova-pylint: https://jenkins.openstack.org/job/nova-pylint
.. _nova-tarball: https://jenkins.openstack.org/job/nova-tarball
