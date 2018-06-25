---
security:
  - |
    To mitigate potential issues with compute nodes disabling
    themselves in response to failures that were either non-fatal or
    user-generated, the consecutive build failure counter
    functionality in the compute service has been changed to advise
    the scheduler of the count instead of self-disabling the service
    upon exceeding the threshold. The
    ``[compute]/consecutive_build_service_disable_threshold``
    configuration option still controls whether the count is tracked,
    but the action taken on this value has been changed to a scheduler
    weigher. This allows the scheduler to be configured to weigh hosts
    with consecutive failures lower than other hosts, configured by the
    ``[filter_scheduler]/build_failure_weight_multiplier`` option. If
    the compute threshold option is nonzero, computes will report their
    failure count for the scheduler to consider. If the threshold
    value is zero, then computes will not report this value
    and the scheduler will assume the number of failures for
    non-reporting compute nodes to be zero. By default, the scheduler
    weigher is enabled and configured with a very large multiplier to
    ensure that hosts with consecutive failures are scored low by
    default.
