#!/bin/bash
# sonobuoy_run.sh
# assume Opni and log adapters are already installed

set -e
sonobuoy run \
--kubeconfig ~/.kube/config \
--namespace "opni-sono" \
--plugin https://raw.githubusercontent.com/jameson-mcghee/opni-insights-service/insights-int-tests-jrm/opni-insights-service/tests/sonobuoy/opnisono-plugin.yaml
sleep 2
for i in {1..5}; do sonobuoy logs -n opni-sono && break || sleep .5; done
for i in {1..60}; do sonobuoy retrieve -n opni-sono && break || sleep 5; done
sonobuoy_status=$(sonobuoy status -n opni-sono --json | jq -r '.plugins[] | select(.plugin=="opni-sonobuoy") | ."result-status"')
if [ "$sonobuoy_status" != "passed" ]; then
  sonobuoy logs -n opni-sono
  echo "SONOBUOY TESTS FAILED! View report for more details"
  exit 1
fi
if [ "$sonobuoy_status" == "passed" ]; then
  echo "SONOBUOY TESTS PASSED!"
  exit 1
fi
sonobuoy delete --wait
kubectl delete ns opni-sono --wait=false