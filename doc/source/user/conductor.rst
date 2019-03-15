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


Conductor as a place for orchestrating tasks
============================================

In addition to its roles as a database proxy and object backporter the
conductor service also serves as a centralized place to manage the execution of
workflows which involve the scheduler.  Rebuild, resize/migrate, and building
an instance are managed here.  This was done in order to have a better
separation of responsibilities between what compute nodes should handle and
what the scheduler should handle, and to clean up the path of execution.
Conductor was chosen because in order to query the scheduler in a synchronous
manner it needed to happen after the API had returned a response otherwise API
response times would increase.  And changing the scheduler call from
asynchronous to synchronous helped to clean up the code.

To illustrate this the old process for building an instance was:

* API receives request to build an instance.

* API sends an RPC cast to the scheduler to pick a compute.

* Scheduler sends an RPC cast to the compute to build the instance, which
  means the scheduler needs to be able to communicate with all computes.

  * If the build succeeds it stops here.

  * If the build fails then the compute decides if the max number of
    scheduler retries has been hit.  If so the build stops there.

    * If the build should be rescheduled the compute sends an RPC cast to the
      scheduler in order to pick another compute.

This was overly complicated and meant that the logic for
scheduling/rescheduling was distributed throughout the code.  The answer to
this was to change to process to be the following:

* API receives request to build an instance.

* API sends an RPC cast to the conductor to build an instance. (or runs
  locally if conductor is configured to use local_mode)

* Conductor sends an RPC call to the scheduler to pick a compute and waits
  for the response.  If there is a scheduler fail it stops the build at the
  conductor.

* Conductor sends an RPC cast to the compute to build the instance.

  * If the build succeeds it stops here.

  * If the build fails then compute sends an RPC cast to conductor to build
    an instance.  This is the same RPC message that was sent by the API.

This new process means the scheduler only deals with scheduling, the compute
only deals with building an instance, and the conductor manages the workflow.
The code is now cleaner in the scheduler and computes.
