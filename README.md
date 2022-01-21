# Opni Insights service

* This repository builds the opni-insights image which sets up an HTTP server. It sets up endpoints for many different insights between any time interval.
    * Breakdown of normal, suspicious and anomalous log message by pod, namespace, workload and control plane component through the insights_breakdown endpoint
    * Overall breakdown of normal, suspicious and anomalous log messages through the overall_insights endpoint.
    * Breakdown of number of anomalies by workload and control plane logs through the anomalies_breakdown endpoint.
    * Log messages of an anomaly level (normal, suspicious or anomaly) that are broken down by pod, namespace, workload and control plane components.
      * Get log messages for a specific pod, namespace and anomaly level through the logs_pod endpoint.
      * Get log messages for a specific namespace and anomaly level through the logs_namespace endpoint.
      * Get log messages for a specific workload and anomaly level through the logs_workload endpoint.
      * Get log messages for a control plane component and anomaly level through the logs_control_plane endpoint.
    * Areas of interest based on the number of anomalies per minute through the areas_of_interest endpoint.
    * Peak detection based on the number of anomalies per minute through the peaks endpoint.
### Setup RBAC permissions
```
kubectl apply -f rbac.yaml
```

### Methodology
* To try out the opni-insights-service, you can first port-forward the service.
```
kubectl port-forward svc/opni-insights-service 8000:80
```
* These are the specified parameters for each of the endpoints
  * insights_breakdown: start_ts (integer), end_ts (integer)
  * overall_insights: start_ts (integer), end_ts (integer), granularity_level (string) in the format of number and unit (ex: 1 hour is 1h, 10 minutes is 10m)
  * anomalies_breakdown: start_ts (integer), end_ts (integer)
  * logs_pod: start_ts (integer), end_ts (integer), anomaly_level (string), pod_name (string), namespace_name (string), scroll_id (string, Optional)
  * logs_namespace: start_ts (integer), end_ts (integer), anomaly_level (string), namespace_name (string), scroll_id (string, Optional)
  * logs_workload: start_ts (integer), end_ts (integer), anomaly_level (string), namespace_name (string), workload_type (string), workload_name (string), scroll_id (string, Optional)
  * logs_control_plane: start_ts (integer), end_ts (integer), anomaly_level (string), control_plane_component (string), scroll_id (string, Optional)
  * areas_of_interest: start_ts (integer), end_ts (integer)
  * peaks: start_ts (integer), end_ts (integer)

* Then, send a get request to the endpoint to fetch insight data on pods, namespaces, workloads, logs or overall insights and specify the starting and ending time intervals to query that data from.

* For example, to fetch the overall breakdown of log messages between the timestamps 1638402415000 and 1642402415000 with a granularity of 1 hour, you can run this command to make a Get request to the workload endpoint:
```
curl --location --request GET 'localhost:8000/overall_insights?start_ts=1638402415000&end_ts=1642402415000&granularity_level=1h' --header 'Content-Type: application/json'
```
* To fetch log messages of specified anomaly level ANOMALY_LEVEL for a pod POD_NAME within a specified namespace NAMESPACE_NAME between a starting and ending timestamp, you can run this command to make a Get request to the logs endpoint which will fetch 100 logs.
```
curl --location --request GET 'localhost:8000/logs?start_ts=1631794584000&end_ts=1631855784000&anomaly_level=ANOMALY_LEVEL&namespace_name=NAMESPACE_NAME&pod_name=POD_NAME' --header 'Content-Type: application/json'
```
In addition to returning 100 log messages as part of the current page, it will also return a scroll_id which can be used to access subsequent pages of log messages.

* To fetch log messages for a pod POD_NAME within a specified namespace NAMESPACE_NAME between a starting and ending timestamp and with a specified scroll_id, you can run this command to make a Get request to the logs endpoint which will fetch the next 100 logs from the reference of the scroll_id.
```
curl --location --request GET 'localhost:8000/logs?start_ts=1631794584000&end_ts=1631855784000&anomaly_level=ANOMALY_LEVEL&namespace_name=NAMESPACE_NAME&pod_name=POD_NAME&scroll_id=SCROLL_ID' --header 'Content-Type: application/json'
```




## Contributing
We use `pre-commit` for formatting auto-linting and checking import. Please refer to [installation](https://pre-commit.com/#installation) to install the pre-commit or run `pip install pre-commit`. Then you can activate it for this repo. Once it's activated, it will lint and format the code when you make a git commit. It makes changes in place. If the code is modified during the reformatting, it needs to be staged manually.

```
# Install
pip install pre-commit

# Install the git commit hook to invoke automatically every time you do "git commit"
pre-commit install

# (Optional)Manually run against all files
pre-commit run --all-files
```
