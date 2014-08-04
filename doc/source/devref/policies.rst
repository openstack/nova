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

APIs
=====

Follow the guidelines set in: https://wiki.openstack.org/wiki/APIChangeGuidelines

The canonical source for API behavior is the code *not* documentation.
Documentation is manually generated after the code by folks looking at the
code and writing up what they think it does, and it is very easy to get
this wrong.

This policy is in place to prevent us from making backwards incompatible
changes to APIs.

Patches and Reviews
===================

Merging a patch requires a non-trivial amount of reviewer resources.
As a patch author, you should try to offset the reviewer resources
spent on your patch by reviewing other patches. If no one does this, the review
team (cores and otherwise) become spread too thin.

For review guidelines see: https://wiki.openstack.org/wiki/ReviewChecklist
