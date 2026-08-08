#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import enum
import functools
import multiprocessing
import queue
import threading
import time
import typing as ty

import futurist
from oslo_context import context as common_context
from oslo_log import log as logging
from oslo_utils import importutils

import nova.conf
from nova import utils

profiler = importutils.try_import('osprofiler.profiler')

CONF = nova.conf.CONF

LOG = logging.getLogger(__name__)

# NOTE(gibi): futurist does not expose the common based class.
# NOTE(gibi): we can simplify this when eventlet is removed.
Executor: ty.TypeAlias = (
    futurist.GreenThreadPoolExecutor | futurist.ThreadPoolExecutor)


def get_max_concurrent_builds():
    if CONF.max_concurrent_builds > 0:
        return CONF.max_concurrent_builds

    # setting CONF.max_concurrent_builds to 0 (unlimited)
    # is deprecated but still supported, so we need to use a sane
    # default values for each threading mode
    LOG.warning("Nova compute deprecated the support of unlimited "
                "parallel instance builds so "
                "[DEFAULT]max_concurrent_builds configured "
                "with value 0 is deprecated and will not be supported "
                "in future releases. Please set an explicit positive "
                "value to this config option instead.")
    if utils.concurrency_mode_threading():
        # Fall back to the default of the config
        return 10
    else:
        # In eventlet mode we need to keep backward compatibility, and
        # we use 1000 to emulate unlimited
        return 1000


def get_max_concurrent_snapshots():
    if CONF.max_concurrent_snapshots > 0:
        return CONF.max_concurrent_snapshots

    # setting CONF.max_concurrent_snapshots to 0 (unlimited)
    # is deprecated but still supported, so we need to use a sane
    # default values for each threading mode
    LOG.warning("Nova compute deprecated the support of unlimited "
                "parallel instance snapshots so "
                "[DEFAULT]max_concurrent_snapshots configured "
                "with value 0 is deprecated and will not be supported "
                "in future releases. Please set an explicit positive "
                "value to this config option instead.")
    if utils.concurrency_mode_threading():
        # Fall back to the default of the config
        return 5
    else:
        # In eventlet mode we need to keep backward compatibility, and
        # we use 1000 to emulate unlimited
        return 1000


def get_max_concurrent_live_migrations():
    if CONF.max_concurrent_live_migrations > 0:
        return CONF.max_concurrent_live_migrations

    # setting CONF.max_concurrent_live_migrations to 0 (unlimited)
    # is deprecated but still supported, so we need to use a sane
    # default values for each threading mode
    LOG.warning("Nova compute deprecated the support of unlimited "
                "parallel live migration so "
                "[DEFAULT]max_concurrent_live_migrations configured "
                "with value 0 is deprecated and will not be supported "
                "in future releases. Please set an explicit positive"
                "value to this config option instead.")
    if utils.concurrency_mode_threading():
        return 5
    else:
        # In eventlet mode we need to keep backward compatibility and
        # 1000 greenthreads to emulate unlimited
        return 1000


class ExecutorType(enum.Enum):
    """The process wide singleton executors.

    The enum value is used both as the executor's name suffix and
    as the key which ThreadPoolFactory tracks it.
    """
    DEFAULT = "default"
    SCATTER_GATHER = "cell_worker"
    CACHE_IMAGES = "cache_images"
    LONG_TASK = "long_task"
    SYNC_POWER = "sync_power_state"
    LIVE_MIGRATION = "live_migration"


class ExecutorsPoolSize:
    """Sizing for every singleton executor."""

    @staticmethod
    def _default_pool_size():
        return (
            CONF.default_thread_pool_size if utils.concurrency_mode_threading()
            else CONF.default_green_pool_size)

    @staticmethod
    def _scatter_gather_pool_size():
        return (
            CONF.cell_worker_thread_pool_size
            if utils.concurrency_mode_threading() else 1000)

    @staticmethod
    def _cache_images_pool_size():
        return CONF.image_cache.precache_concurrency

    @staticmethod
    def _sync_power_pool_size():
        return CONF.sync_power_state_pool_size

    @staticmethod
    def _long_task_pool_size():
        max_builds = get_max_concurrent_builds()
        max_snapshots = get_max_concurrent_snapshots()

        if utils.concurrency_mode_threading():
            max_tasks = max(max_builds, max_snapshots)

            if max_builds != max_snapshots:
                LOG.warning(
                    "In native threading mode the number of concurrent "
                    "builds, and snapshots should be limited to the "
                    "same number. The current configuration has differing "
                    "limits: max_concurrent_builds: %d, "
                    "max_concurrent_snapshots: %d. "
                    "Nova will use a single, overall limit of %d for these "
                    "tasks.",
                    max_builds, max_snapshots, max_tasks)
        else:
            # In eventlet mode we use the individual build/snapshot
            # semaphores to limit the concurrent tasks, so just size the
            # pool to potentially host all of them.
            return max_builds + max_snapshots
        return max_tasks

    _EXECUTOR_POOL_SIZE = {
        ExecutorType.DEFAULT: _default_pool_size,
        ExecutorType.SCATTER_GATHER: _scatter_gather_pool_size,
        ExecutorType.CACHE_IMAGES: _cache_images_pool_size,
        ExecutorType.LONG_TASK: _long_task_pool_size,
        ExecutorType.SYNC_POWER: _sync_power_pool_size,
        ExecutorType.LIVE_MIGRATION: get_max_concurrent_live_migrations,
    }

    @classmethod
    def get(cls, executor_type):
        return cls._EXECUTOR_POOL_SIZE[executor_type]()


class ThreadPoolFactory:
    """Lifecycle management factory of every thread pool executors.

    This provides the single entry point for to create and get the thread
    pool executors. It create the singleton executors and those are tracked
    for central management.

    Every executor created through this factory is tracked so that
    we do not need to know every individual executors for cleanup/shutdown
    and shutdown_all() can be used as a common way to shut down all of them.
    """

    def __init__(self):
        # NOTE(gmaan): This lock makes executor creation and shutdown mutual
        # exclusive so that no new executor can be created once shutdown has
        # started.
        self._shutdown_lock = threading.Lock()
        self._shutdown = False
        self._all_executors = {}

    def _new_executor(self, max_workers, name):
        """Create a new executor."""
        if utils.concurrency_mode_threading():
            executor = futurist.ThreadPoolExecutor(max_workers)
        else:
            executor = futurist.GreenThreadPoolExecutor(max_workers)

        pname = multiprocessing.current_process().name
        executor.name = f"{pname}.{name}"

        return executor

    def get_executor(self, executor_type):
        """Return the shared, process-wide singleton executor for
        `executor_type`, lazily creating it the first time it is requested,
        sized via ExecutorsPoolSize.
        """
        executor = self._all_executors.get(executor_type)
        if not executor:
            with self._shutdown_lock:
                if self._shutdown:
                    raise RuntimeError(
                        "Cannot create the %s thread pool executor because "
                        "shutdown has been started." %
                        executor_type.value)
                executor = self._all_executors.get(executor_type)
                if not executor:
                    max_workers = ExecutorsPoolSize.get(executor_type)
                    executor = self._new_executor(
                        max_workers, executor_type.value)
                    self._all_executors[executor_type] = executor
                    LOG.info(
                        "The %s thread pool %s is initialized",
                        executor_type.value, executor.name)

        return executor

    def _teardown_all(self, mark_shutdown=True):
        with self._shutdown_lock:
            if mark_shutdown:
                self._shutdown = True
            executors = list(self._all_executors.values())
            self._all_executors.clear()

        for executor in executors:
            name = getattr(executor, "name")
            LOG.info("The thread pool %s is shutting down", name)
            executor.shutdown(wait=True)
            LOG.info("The thread pool %s is shutdown", name)

    def shutdown_all(self):
        """Shuts down every executor created via get_executor() so far.

        Services create different sets of executors depending on what they
        need. Since get_executor() registers every executor it creates,
        this gives nova.service.Service's graceful shutdown flow a single,
        common call to shut all of them down at the end.

        Every executor is shut down with wait=True, so this call blocks until
        the slowest executor has drained its in-progress work.

        NOTE: This permanently marks this factory as shutdown (set
        self._shutdown=True), after which get_executor() will always raise.
        Use this only for a process's real graceful shutdown (e.g. on
        SIGTERM), never as a way to just reset/clear the executors. For
        example, scheduler and conductor service use os.fork() to create
        their worker instance which copies this flag into every worker,
        so calling this on a process that will go on to fork workers will
        permanently break executor creation in all of them. Use reset_all()
        for that case instead.
        """
        self._teardown_all()

    def reset_all(self):
        """Reset/Clear every executor.

        This shuts down every executor with wait=True and clears
        self._all_executors but does not set any flag/state on this factory.
        That is the difference from shutdown_all(). It is used before the
        main process uses os.fork() to create multiple workers. Any executor
        created in the parent or this factory state must not be inherited by
        the forked worker. Use this when you need to clear the executors but
        do not want to mark this thread pool factory as shutdown.

        TODO(gmaan): Once we make our services to use spawn instead of fork
        then we do not need this reset_all() or cleanup the threads before
        child process/workers are created.
        """
        self._teardown_all(mark_shutdown=False)


FACTORY = ThreadPoolFactory()


def get_executor(executor_type):
    return FACTORY.get_executor(executor_type)


def shutdown_all_executors():
    """Shutdown every executor of a process."""
    FACTORY.shutdown_all()


def reset_all_executors():
    """Reset every executor of a process.
    """
    FACTORY.reset_all()


def _serialize_profile_info():
    if not profiler:
        return None
    prof = profiler.get()
    trace_info = None
    if prof:
        # FIXME(DinaBelova): we'll add profiler.get_info() method
        # to extract this info -> we'll need to update these lines
        trace_info = {
            "hmac_key": prof.hmac_key,
            "base_id": prof.get_base_id(),
            "parent_id": prof.get_id()
        }
    return trace_info


def _executor_is_full(executor: Executor) -> bool:
    if utils.concurrency_mode_threading():
        # TODO(gibi): Move this whole logic to futurist ThreadPoolExecutor
        # so that we can avoid accessing the internals of the executor
        with executor._shutdown_lock:
            idle_workers = len(
                [w for w in executor._workers if w.idle]) > 0
            queued_tasks = executor._work_queue.qsize() > 0
            return queued_tasks and not idle_workers

    return False


def _log_executor_stats(executor: Executor, executor_type) -> None:
    if CONF.thread_pool_statistic_period < 0:
        return

    last_stats = getattr(executor, "last_stats", None)
    name = executor_type.value

    allowed_stat_age = (
        time.monotonic() - CONF.thread_pool_statistic_period)
    if last_stats and last_stats > allowed_stat_age:
        return

    executor.last_stats = time.monotonic()

    stats: futurist.ExecutorStatistics = executor.statistics

    if isinstance(executor, futurist.ThreadPoolExecutor):
        LOG.debug(
            "State of %s ThreadPoolExecutor when submitting a new "
            "task: max_workers: %d, workers: %d, idle workers: %d, "
            "queued work: %d, stats: %s",
            name,
            executor._max_workers, len(executor._workers),
            len([w for w in executor._workers if w.idle]),
            executor._work_queue.qsize(), stats)
    elif isinstance(executor, futurist.GreenThreadPoolExecutor):
        LOG.debug(
            "State of %s GreenThreadPoolExecutor when submitting a new "
            "task: workers: %d, max_workers: %d, work queued length: "
            "%d, stats: %s",
            name,
            len(executor._pool.coroutines_running), executor._pool.size,
            executor._delayed_work.unfinished_tasks, stats)


def spawn_on(
    executor_type: ExecutorType,
    func: ty.Callable[..., ty.Any],
    *args: ty.Any,
    **kwargs: ty.Any,
) -> futurist.Future:
    """Passthrough method to run func on a thread in the named executor.

    Gets (creating it on first use) the executor for `executor_type` and
    runs func on it.

    It will also grab the context from the threadlocal store and add it to
    the store on the new thread.  This allows for continuity in logging the
    context when using this method to spawn a new thread.
    """
    executor = get_executor(executor_type)

    _log_executor_stats(executor, executor_type)
    if _executor_is_full(executor):
        LOG.warning(
            "The %s pool does not have free threads so the task %s will be "
            "queued. If this happens repeatedly then the size of the pool is "
            "too small for the load or there are stuck threads filling the "
            "pool.", getattr(executor, "name", "unknown"), func)

    _context = common_context.get_current()
    profiler_info = _serialize_profile_info()

    @functools.wraps(func)
    def context_wrapper(*args, **kwargs):
        # NOTE: If update_store is not called after spawning a thread, it won't
        # be available for the logger to pull from threadlocal storage.
        if _context is not None:
            _context.update_store()
        if profiler_info and profiler:
            profiler.init(**profiler_info)
        return func(*args, **kwargs)

    return executor.submit(context_wrapper, *args, **kwargs)


def spawn(
    func: ty.Callable[..., ty.Any],
    *args: ty.Any, **kwargs: ty.Any,
) -> futurist.Future:
    """Passthrough method for eventlet.spawn.

    Always spawns on the shared, default executor. See spawn_on() to spawn
    on a different named executor.

    This utility exists so that it can be stubbed for testing without
    interfering with the service spawns.
    """
    return spawn_on(ExecutorType.DEFAULT, func, *args, **kwargs)


class StaticallyDelayingCancellableTaskExecutorWrapper:
    """Executor wrapper that submit work to another executor but delays each
    task's submission with a statically defined delay and supports cancelling
    the task during such delay.

    Note that tasks that are actually started running in the real executor
    might not be cancellable anymore depending on that executor and the
    concurrency mode used. See
    https://docs.python.org/3.12/library/concurrent.futures.html#concurrent.futures.Future.cancel

    Note that shutting down the wrapper only shuts down its own scheduler
    thread but does not shut down the real executor that is passed in __init__.

    Note that this class does not support a different delay length for
    different tasks.
    """

    class Task:
        def __init__(
            self,
            delay: float,
            fn: ty.Callable[..., ty.Any],
            args: tuple,
            kwargs: dict
        ):
            self.deadline = time.monotonic() + delay
            self.future = futurist.Future()
            self.fn = fn
            self.args = args
            self.kwargs = kwargs

        @property
        def remaining_delay(self):
            return self.deadline - time.monotonic()

        def __str__(self):
            return (
                f"Task(fn={self.fn}, "
                f"remaining_delay={self.remaining_delay} "
                f"future={self.future})")

    def __init__(self, delay: float, executor: Executor):
        """Initialize the wrapper

        :param delay: delay length in seconds
        :param executor: executor object to run each task. It supports both
            native threading and eventlet based executors.
        """

        self._queue: queue.Queue = queue.Queue()
        self._executor = executor
        self._delay = delay
        self._shutdown = threading.Condition()
        self._shutdown_requested = False
        self._sentinel = self.Task(0, lambda: None, (), {})
        # We are intentionally not running our _run() in the executor
        # as we cannot assume that the executor has more than one worker
        # and our logic never finishes so it would consume one worker
        # constantly.
        self._thread = threading.Thread(target=self._run)
        self._thread.daemon = True
        self._thread.start()

    @staticmethod
    def _log(msg, *args):
        LOG.debug(msg, *args)

    @staticmethod
    def _task_wrapper(task) -> None:
        """This wraps the original task so when it finishes in the real
        executor the result of the task can be copied to the Future object
        already returned to our caller from submit_with_delay(). So
        the caller can get the result or exception from the task.
        """
        try:
            task.future.set_result(task.fn(*task.args, **task.kwargs))
        except BaseException as e:
            task.future.set_exception(e)

    def _wait_for_deadline_then_set_running(self, task) -> bool:
        """Waiting for the task's deadline then mark it running

        Wait can be interrupted by shutdown of the wrapper in such a case
        the task's state is checked. If the task is cancelled then return
        immediately with False. If the task is not cancelled then wait for
        its deadline and eventually return True if the task is still not
        cancelled.

        If True is returned the future in the task is also atomically set to
        running state and the future cannot be cancelled anymore.
        """
        if task.remaining_delay <= 0:
            return task.future.set_running_or_notify_cancel()

        self._log("Waitig for the deadline of %s", task)
        with self._shutdown:
            shutdown = self._shutdown.wait_for(
                lambda: self._shutdown_requested, task.remaining_delay)

        if shutdown:
            self._log(
                "Shutdown is requested while waiting "
                "for the deadline of %s", task)

            if task.future.cancelled():
                return False

            self._log(
                "%s is not cancelled so still waiting for its "
                "deadline", task)
            if task.remaining_delay > 0:
                # Blocking here is fine as we have the assumption that
                # no new task can arrive that has a deadline that is sooner
                # than the deadline of the oldest task in the queue due to
                # our static delay (and we assume that time travel is not
                # allowed).
                time.sleep(task.remaining_delay)

        return task.future.set_running_or_notify_cancel()

    def _run(self):
        while True:
            self._log("Waiting for the next task")
            task: StaticallyDelayingCancellableTaskExecutorWrapper.Task = (
                self._queue.get())
            self._log("Received %s", task)

            if task is self._sentinel:
                # We are asked to terminate so exit the loop.
                self._queue.task_done()
                self._log("Sentinel received, thread is exiting")
                return

            if task.future.cancelled():
                # The task was cancelled while it was in the queue.
                # We don't need to run it. Just move on to the next task
                self._log("%s was cancelled while queued, skipping", task)
                self._queue.task_done()
                continue

            # The task is still valid, wait for its deadline
            run_it = self._wait_for_deadline_then_set_running(task)
            if not run_it:
                # The task was cancelled during the delay period.
                # We don't need to run it. Just move on to the next task.
                self._log(
                    "%s was cancelled during its delay period, skipping", task)
                self._queue.task_done()
                continue

            # Push the task to the real executor. We don't need to wait
            # for the result here as the client can do that
            # via the task.future we already returned from submit_with_delay()
            try:
                self._executor.submit(self._task_wrapper, task)
            except BaseException as e:
                # If for any reason we cannot submit a task then we should not
                # let the exception escape as that will prevent our thread
                # to terminate cleanly. Instead, we log and propagate back.
                LOG.exception(
                    "Failed to submit %s to executor %s", task, self._executor)
                task.future.set_exception(e)
                self._queue.task_done()
                continue

            self._log("%s submitted to %s", task, self._executor)
            # The task is not done from the executor perspective, but it is
            # done from the _run() logic perspective. Signal it, so shutdown()
            # can use Queue.join()
            self._queue.task_done()

    def submit_with_delay(
        self, fn: ty.Callable[..., ty.Any], *args: ty.Any, **kwargs: ty.Any
    ) -> futurist.Future:
        """Submit work with delay."""
        # We need this wide locking as we don't want to queue a task behind
        # the sentinel as that task will never be processed.
        with self._shutdown:
            if self._shutdown_requested:
                raise RuntimeError(
                    "Cannot schedule new tasks after being shutdown")

            task = self.Task(self._delay, fn, args, kwargs)
            self._queue.put(task)
            self._log("Queued %s", task)
            return task.future

    def shutdown(self, wait: bool = True):
        """Shutdown the executor"""
        with self._shutdown:
            if not self._shutdown_requested:
                # Ensure that our thread wakes at least one more time to allow
                # it to exit by queuing up a sentinel task after the shutdown
                # condition is set. This task won't be executed.
                self._queue.put(self._sentinel)
                self._log("Sentinel is queued")
                self._shutdown_requested = True
                self._shutdown.notify_all()
                self._log("Shutdown is set")

        # If wait is set we need to wait for our sentinel to be processed and
        # therefore our thread to exit.
        # NOTE(gibi): We are intentionally not shutting down the real executor
        # as we are not the one created it or owning it so it might be shared
        # between different callers.
        if wait:
            self._queue.join()
            self._log("Queue joined")
            self._thread.join()
            self._log("Scheduler thread joined")

    @property
    def is_alive(self) -> bool:
        return self._thread.is_alive()
