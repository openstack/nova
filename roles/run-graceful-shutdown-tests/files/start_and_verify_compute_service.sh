#!/bin/bash
set -x
set -e

COMPUTE_HOST=$1
EXPECTED_STATE=${2:-active}
INTERVAL=${3:-10}
TIMEOUT=${4:-60}

get_service_status() {
  local host=$1
  local status
  status=$(ssh "${host}" systemctl is-active devstack@n-cpu || true)
  echo "${status}"
}

wait_for_service_state() {
  local host=$1
  local expected=$2
  local interval=$3
  local timeout=$4
  local elapsed=0
  local status
  local start_time
  start_time=$(date)

  echo "Started checking compute service on ${host} for state '${expected}' at ${start_time} (interval=${interval}s, timeout=${timeout}s)"

  status=$(get_service_status "${host}")
  while [ "${status}" != "${expected}" ]; do
    sleep "${interval}"
    elapsed=$((elapsed + interval))
    if [ ${elapsed} -ge ${timeout} ]; then
      echo "Timed out waiting for compute service on ${host} to be ${expected} (current: ${status}); started at ${start_time}, waited ${elapsed}s"
      exit 5
    fi
    status=$(get_service_status "${host}")
  done
  echo "Compute service on ${host} is ${expected}; started at ${start_time}, took ${elapsed}s"
}

if [ "${EXPECTED_STATE}" == "active" ] && [ "$(get_service_status "${COMPUTE_HOST}")" != "active" ]; then
    ssh "${COMPUTE_HOST}" sudo systemctl start devstack@n-cpu
fi

wait_for_service_state "${COMPUTE_HOST}" "${EXPECTED_STATE}" "${INTERVAL}" "${TIMEOUT}"
