# Standard Library
import asyncio
import logging
import os

import pandas as pd

# Third Party
from elasticsearch import AsyncElasticsearch
from kubernetes import client, config
from PeakDetecion import PeakDetection

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(message)s")

config.load_incluster_config()
configuration = client.Configuration()
core_api_instance = client.CoreV1Api()
app_api_instance = client.AppsV1Api()

ES_ENDPOINT = os.environ["ES_ENDPOINT"]
ES_USERNAME = os.environ["ES_USERNAME"]
ES_PASSWORD = os.environ["ES_PASSWORD"]
es_instance = AsyncElasticsearch(
    [ES_ENDPOINT],
    port=9200,
    http_compress=True,
    http_auth=(ES_USERNAME, ES_PASSWORD),
    verify_certs=False,
    use_ssl=True,
)

WINDOW = int(os.getenv("WINDOW", "10"))
THRESHOLD = float(os.getenv("THRESHOLD", "2.5"))
INFLUENCE = float(os.getenv("INFLUENCE", "0.5"))
AOI_MINUTES_THRESHOLD = int(os.getenv("AOI_MINUTES_THRESHOLD", "10"))
MILLISECONDS_MINUTE = 60000


historic_workload_data = dict()
historic_workload_pod_dict = dict()
workload_types = {
    "ReplicaSet",
    "StatefulSet",
    "Deployment",
    "Job",
    "DaemonSet",
    "CustomResource",
    "Independent",
}

class BackgroundFunction:
    def __init__(self):
        pass

    def get_next_owner_reference_metadata(self, all_workload_data, owner_name):
        """
        This function is called by get_workload_name and takes in a list of metadata objects of a particular workload type
        (deployment, statefulset, replicaset or daemonset) and a string for the owner name. It will then go through
        the list of metadata objects, until it comes across the object which matches the owner name and then returns that
        metadata object. If no metadata object is found, return None which will cause the while loop in get_workload_name
        to break.
        """
        for data_idx in range(len(all_workload_data)):
            if all_workload_data[data_idx].metadata.name == owner_name:
                return all_workload_data[data_idx].metadata

    def get_workload_name(self, pod_metadata):
        """
        This function gets the name of the workload by looping through owner references until it reaches a workload which
        does not have an owner reference. When it reaches that workload, it then is able to retrieve the name of that workload.
        """

        owner_name = None
        # While loop that will keep on looping until it comes across an object which does not have an owner reference.
        while pod_metadata and pod_metadata.owner_references:
            owner_references = pod_metadata.owner_references
            if len(owner_references) == 0:
                break
            owner_kind = owner_references[0].kind
            owner_name = owner_references[0].name
            # Depending on the kind of owner_reference, fetch the appropriate breakdown type and obtain the updated pod_metadata.
            if owner_kind == "Deployment":
                all_deployments = (
                    app_api_instance.list_deployment_for_all_namespaces().items
                )
                pod_metadata = self.get_next_owner_reference_metadata(
                    all_deployments, owner_name
                )
            elif owner_kind == "StatefulSet":
                all_stateful_sets = (
                    app_api_instance.list_stateful_set_for_all_namespaces().items
                )
                pod_metadata = self.get_next_owner_reference_metadata(
                    all_stateful_sets, owner_name
                )
            elif owner_kind == "ReplicaSet":
                all_replica_sets = (
                    app_api_instance.list_replica_set_for_all_namespaces().items
                )
                pod_metadata = self.get_next_owner_reference_metadata(
                    all_replica_sets, owner_name
                )
            elif owner_kind == "DaemonSet":
                all_daemon_sets = (
                    app_api_instance.list_daemon_set_for_all_namespaces().items
                )
                pod_metadata = self.get_next_owner_reference_metadata(
                    all_daemon_sets, owner_name
                )
            else:
                break

        return owner_name

    async def monitor_workloads(self):
        # This function will call the Kubernetes API every minute to keep track of workloads over time and update historic_workload_data dictionary.
        while True:
            try:
                all_pods = core_api_instance.list_pod_for_all_namespaces(watch=False)
                all_pods_items = all_pods.items
                for pod_spec in all_pods_items:
                    # For each pod object. obtain the name, metadata and owner references.
                    pod_metadata = pod_spec.metadata
                    pod_name = pod_metadata.name
                    namespace_name = pod_metadata.namespace
                    owner_references = pod_metadata.owner_references
                    kind = "CustomResource"
                    workload_name = pod_metadata.name
                    # Determine the kind of breakdown of the pod and update the workload name as well to the name of the owner reference.
                    if owner_references and len(owner_references) > 0:
                        if owner_references[0].kind in workload_types:
                            kind = owner_references[0].kind
                        workload_name = owner_references[0].name
                    else:
                        kind = "Independent"
                    original_workload_name = self.get_workload_name(pod_metadata)
                    if original_workload_name:
                        workload_name = original_workload_name
                    if not namespace_name in historic_workload_data:
                        historic_workload_data[namespace_name] = {
                            "ReplicaSet": {},
                            "StatefulSet": {},
                            "Deployment": {},
                            "Job": {},
                            "DaemonSet": {},
                            "CustomResource": {},
                            "Independent": {},
                        }
                        historic_workload_pod_dict[namespace_name] = historic_workload_data[namespace_name]
                    if not workload_name in historic_workload_pod_dict[namespace_name][kind]:
                        historic_workload_pod_dict[namespace_name][kind][workload_name] = []
                    if not pod_name in historic_workload_data[namespace_name][kind][workload_name]:
                        historic_workload_pod_dict[namespace_name][kind][workload_name].append(pod_name)
                    if not pod_name in historic_workload_data[namespace_name][kind]:
                        historic_workload_data[namespace_name][kind][
                            pod_name
                        ] = workload_name

            except Exception as e:
                logging.error(f"Unable to access Kubernetes pod endpoint. {e}")
            await asyncio.sleep(60)

async def get_logs(start_ts, end_ts, query_parameters, scroll_id):
    """
    This function takes a start_ts, end_ts, a dictionary called query_parameters and a scroll_id. The contents of query_parameters
    depends on which endpoint a Get request was submitted to. type of data is being filtered for though the

    100 logs marked as Suspicious or Anomoly and additional attributes such as the timestamp, anomaly_level,
    whether or not it is a control plane log, pod name and namespace name based on the page number specified. If the scroll_id
    is None, fetch the first 100 logs during the specified time interval and also provide the scroll_id as a returned argument.
    If a scroll_id is provided, fetch the next 100 logs from the reference of the scroll_id and return the new scroll_id upon
    returning the logs_dict dictionary.
    """
    logs_dict = {"Logs": []}
    try:
        query_body = {
            "query": {
                "bool": {
                    "filter": [{"range": {"timestamp": {"gte": start_ts, "lte": end_ts}}}],
                    "must": [{"match": {"anomaly_level": query_parameters["anomaly_level"]}}],
                },
            },
            "_source": [
                "timestamp",
                "log",
                "anomaly_level",
                "is_control_plane_log",
                "kubernetes.pod_name",
                "kubernetes.namespace_name",
            ],
            "sort": [{"timestamp": {"order": "asc"}}],
        }
        # Separate query for counting the total number of logs within the time interval.
        count_query_body = {
            "query": {
                "bool": {
                    "filter": [
                        {"range": {"timestamp": {"gte": start_ts, "lte": end_ts}}}],
                    "must": [{"match": {"anomaly_level": query_parameters["anomaly_level"]}}],
                },
            },
        }
    except Exception as e:
        logging.error("anomaly_level not provided in query_parameters dictionary")
        return logs_dict

    # If the logs_pod endpoint is hit, extract the pod_name and namespace_name from the query_parameters dictionary.
    if query_parameters["type"] == "pod":
        try:
            query_body["query"]["bool"]["must"].append({"match": {"kubernetes.namespace_name.keyword": query_parameters["namespace_name"]}})
            query_body["query"]["bool"]["must"].append({"match": {"kubernetes.pod_name.keyword": query_parameters["pod_name"]}})
            count_query_body["query"]["bool"]["must"].append({"match": {"kubernetes.namespace_name.keyword": query_parameters["namespace_name"]}})
            count_query_body["query"]["bool"]["must"].append({"match": {"kubernetes.pod_name.keyword": query_parameters["pod_name"]}})
        except Exception as e:
            logging.error(f"Proper arguments not provided to query_parameters. {e}")
            return logs_dict

    # If the logs_namespace endpoint is hit, extract namespace_name from the query_parameters dictionary.
    elif query_parameters["type"] == "namespace":
        try:
            query_body["query"]["bool"]["must"].append({"match": {"kubernetes.namespace_name.keyword": query_parameters["namespace_name"]}})
            count_query_body["query"]["bool"]["must"].append({"match": {"kubernetes.namespace_name.keyword": query_parameters["namespace_name"]}})
        except Exception as e:
            logging.error(f"Proper arguments not provided to query_parameters. {e}")
            return logs_dict

    # If the logs_workload endpoint is hit, extract namespace_name, workload_type and workload_name from query_parameters dictionary.
    elif query_parameters["type"] == "workload":
        try:
            workload_pod_names = historic_workload_pod_dict[query_parameters["namespace_name"]][query_parameters["workload_type"]][query_parameters["workload_name"]]
            should_query = {"bool": {"should": []}}
            for pod_name in workload_pod_names:
                should_query["bool"]["should"].append({"match": {"kubernetes.pod_name.keyword": pod_name}})
            query_body["query"]["bool"]["must"].append({"match": {"kubernetes.namespace_name.keyword": query_parameters["namespace_name"]}})
            count_query_body["query"]["bool"]["must"].append({"match": {"kubernetes.namespace_name.keyword": query_parameters["namespace_name"]}})
            query_body["query"]["bool"]["must"].append(should_query)
            count_query_body["query"]["bool"]["must"].append(should_query)
        except Exception as e:
            logging.error(f"Unable to get logs by workload. {e}")
            return logs_dict

    # If the logs_control_plane endpoint is hit, extract the control_plane_component from the query_parameters dictionary.
    elif query_parameters["type"] == "control_plane":
        try:
            query_body["query"]["bool"]["must"].append({"match": {"kubernetes_component.keyword": query_parameters["control_plane_component"]}})
            query_body["_source"].append("kubernetes_component")
            count_query_body["query"]["bool"]["must"].append({"match": {"kubernetes_component.keyword": query_parameters["control_plane_component"]}})
        except Exception as e:
            logging.error(f"Proper arguments not provided to query_parameters. {e}")
            return logs_dict

    scroll_value = "1m"
    # If scroll_id is provided, then use it to fetch the next 100 logs and return that in addition to the updated scroll_id as part of the logs_dict dictionary.
    try:
        if scroll_id:
            current_page = await es_instance.scroll(scroll_id=scroll_id, scroll=scroll_value)
        else:
            current_page = await es_instance.search(index="logs",body=query_body, scroll=scroll_value, size=100)
        logs_dict["total_logs_count"] = (await es_instance.count(index="logs",body=count_query_body))['count']
        result_hits = current_page["hits"]["hits"]
        logs_dict["scroll_id"] = current_page["_scroll_id"]
        for each_hit in result_hits:
            logs_dict["Logs"].append(each_hit["_source"])
        return logs_dict
    except Exception as e:
        logging.error(f"Unable to access Elasticsearch logs index. {e}")
        return logs_dict

def get_workload_breakdown(pod_breakdown_data):
    # Get the breakdown of normal, suspicious and anomalous logs by workload.
    workload_breakdown_dict = {
        "ReplicaSet": {},
        "StatefulSet": {},
        "Deployment": {},
        "Job": {},
        "DaemonSet": {},
        "CustomResource": {},
        "Independent": {},
    }
    workload_namespace_dict = dict()

    for pod_spec in pod_breakdown_data["Pods"]:
        pod_name, pod_insights, pod_ns = (
            pod_spec["Name"],
            pod_spec["Insights"],
            pod_spec["Namespace"],
        )
        # For each pod object fetch the workload if the data is available.
        workload_name = ""
        kind = ""
        if pod_ns in historic_workload_data:
            for workload_type in historic_workload_data[pod_ns]:
                if pod_name in historic_workload_data[pod_ns][workload_type]:
                    workload_name = historic_workload_data[pod_ns][workload_type][
                        pod_name
                    ]
                    kind = workload_type
                    break
        if workload_name and kind:
            if not workload_name in workload_namespace_dict:
                workload_namespace_dict[workload_name] = pod_ns
            if not workload_name in workload_breakdown_dict[kind]:
                workload_breakdown_dict[kind][workload_name] = {
                    "Normal": 0,
                    "Suspicious": 0,
                    "Anomaly": 0,
                }
            # Accumulate the insight count for each workload name.

            for anomaly_level in workload_breakdown_dict[kind][workload_name]:
                workload_breakdown_dict[kind][workload_name][
                    anomaly_level
                ] += pod_insights[anomaly_level]

    # Restructure workload_breakdown_dict to be in finalized format.
    for breakdown_type, breakdown_dict in workload_breakdown_dict.items():
        workload_breakdown_dict[breakdown_type] = []
        for name, insights in breakdown_dict.items():
            workload_breakdown_dict[breakdown_type].append(
                {
                    "Name": name,
                    "Namespace": workload_namespace_dict[name],
                    "Insights": insights,
                }
            )
    return workload_breakdown_dict

def get_pod_breakdown(pod_aggregation_data):
    # Get the breakdown of normal, suspicious and anomalous logs by pod.
    pod_breakdown_dict = {"Pods": []}
    pod_aggregation_dict = dict()
    try:
        for batch in pod_aggregation_data:
            for each_result in batch:
                namespace_name, pod_name, anomaly_level = each_result["key"]["namespace_name"], each_result["key"]["pod_name"], each_result["key"]["anomaly_level"]
                if not namespace_name in pod_aggregation_dict:
                    pod_aggregation_dict[namespace_name] = dict()
                if not pod_name in pod_aggregation_dict[namespace_name]:
                    pod_aggregation_dict[namespace_name][pod_name] = {"Normal": 0, "Suspicious": 0, "Anomaly": 0}
                pod_aggregation_dict[namespace_name][pod_name][anomaly_level] = each_result["doc_count"]

        for ns_name in pod_aggregation_dict:
            for pod_name in pod_aggregation_dict[ns_name]:
                pod_breakdown_dict["Pods"].append({"Name": pod_name, "Namespace": ns_name, "Insights": pod_aggregation_dict[ns_name][pod_name]})
        return pod_breakdown_dict
    except Exception as e:
        logging.error(f"Unable to aggregate pod data. {e}")
        return pod_breakdown_dict

async def get_aggregated_data(query_body):
    # Given an Elasticsearch query, fetch all results using composite aggregation.
    all_aggregation_results = []
    while True:
        try:
            aggregation_results = (await es_instance.search(index="logs", body=query_body))
            # If an after_key is present, use it to fetch the next batch of aggregations from Elasticsearch. Otherwise, return all aggregations.
            if "after_key" in aggregation_results["aggregations"]["bucket"]:
                after_key = aggregation_results["aggregations"]["bucket"]["after_key"]
                query_body["aggs"]["bucket"]["composite"]["after"] = after_key
                all_aggregation_results.append(aggregation_results["aggregations"]["bucket"]["buckets"])
            else:
                return all_aggregation_results
        except Exception as e:
            logging.error(e)
            return all_aggregation_results

async def get_pod_aggregation(start_ts, end_ts):
    # Get the breakdown of normal, suspicious and anomalous logs by pod and then send over the resulting aggregation to get the pod and workload breakdown.
    other_query_body = {
        "size": 0,
        "query": {
            "bool": {
                "must": [{"match": {"is_control_plane_log": "false"}}, {"regexp": {"kubernetes.namespace_name": ".+"}}],
                "filter": [{"range": {"timestamp": {"gte": start_ts, "lte": end_ts}}}],
            }
        },
        "aggs": {
            "bucket": {
                "composite": {
                    "size": 1000,
                    "sources": [{"namespace_name": {"terms": {"field":"kubernetes.namespace_name.keyword"}}}, {"pod_name": {"terms": {"field": "kubernetes.pod_name.keyword"}}}, {"anomaly_level": {"terms": {"field": "anomaly_level.keyword"}}}],
                }
            }
        }
    }
    try:
        pod_aggregation_data = await get_aggregated_data(other_query_body)
        pod_breakdown_dict = get_pod_breakdown(pod_aggregation_data)
        workload_breakdown_dict = get_workload_breakdown(pod_breakdown_dict)
        return pod_breakdown_dict, workload_breakdown_dict
    except Exception as e:
        logging.error(f"Unable to breakdown pod insights. {e}")
        return {"Pods": []}, {}

async def get_overall_breakdown(start_ts, end_ts, granularity_level):
    # Get the overall breakdown of normal, suspicious and anomalous logs within start_ts and end_ts broken down by granularity level.
    overall_breakdown_dict = {"Insights": []}
    query_body = {
        "query": {
            "bool": {
                "filter": [{"range": {"timestamp": {"gte": start_ts, "lte": end_ts}}}]
            }
        },
        "aggs": {
            "granularity_results": {
                "date_histogram": {"field": "timestamp", "fixed_interval": granularity_level},
                "aggs": {"anomaly_level": {"terms": {"field": "anomaly_level.keyword"}}},
            }
        },
    }
    try:
        granularity_level_buckets = (
            await es_instance.search(index="logs", body=query_body)
        )["aggregations"]["granularity_results"]["buckets"]
        for each_bucket in granularity_level_buckets:
            granularity_level_insights = {"time_start": each_bucket["key"], "Normal": 0, "Suspicious": 0, "Anomaly": 0}
            for anomaly_level_agg in each_bucket["anomaly_level"]["buckets"]:
                granularity_level_insights[anomaly_level_agg["key"]] = anomaly_level_agg["doc_count"]
            overall_breakdown_dict["Insights"].append(granularity_level_insights)
    except Exception as e:
        logging.error(f"Unable to access Elasticsearch data. {e}")
        return overall_breakdown_dict
    return overall_breakdown_dict


async def get_anomalies_breakdown(start_ts, end_ts):
    # Get the number of anomalies based on workload and control plane logs.
    anomaly_breakdown_dict = {"Workload": 0, "Control Plane": 0}
    query_body = {
        "query": {
            "bool": {
                "must": [{"match": {"anomaly_level": "Anomaly"}}],
                "filter": [{"range": {"timestamp": {"gte": start_ts, "lte": end_ts}}}],
            }
        },
        "aggs": {"anomaly_breakdown": {"terms": {"field": "is_control_plane_log"}}},
    }
    try:
        anomaly_level_buckets = (
            await es_instance.search(index="logs", body=query_body)
        )["aggregations"]["anomaly_breakdown"]["buckets"]
        for each_bucket in anomaly_level_buckets:
            if each_bucket["key"]:
                anomaly_breakdown_dict["Control Plane"] = each_bucket["doc_count"]
            else:
                anomaly_breakdown_dict["Workload"] = each_bucket["doc_count"]

    except Exception as e:
        logging.error(f"Unable to access Elasticsearch data. {e}")
        return anomaly_breakdown_dict
    return anomaly_breakdown_dict

async def get_peaks(start_ts, end_ts):
    # This function handles get requests for fetching peaks in number of anomalies predicted within a start and end time interval.
    logging.info(
        f"Received request to obtain all peaks with respect to number of anomalies within {start_ts} and {end_ts}"
    )
    pd_model = PeakDetection(WINDOW, THRESHOLD, INFLUENCE)
    peak_timestamps = []
    query = {
        "query": {
            "bool": {
                "must": [{"match": {"anomaly_level.keyword": "Anomaly"}}],
                "filter": [{"range": {"timestamp": {"gte": start_ts, "lte": end_ts}}}],
            }
        },
        "aggs": {
            "logs_over_time": {
                "date_histogram": {"field": "timestamp", "calendar_interval": "minute"},
                "aggs": {"total_normal": {"sum": {"field": "anomaly_predicted_count"}}},
            }
        }
    }
    try:
        res = await es_instance.search(index="logs", body=query, size=0)
        df = pd.DataFrame(res["aggregations"]["logs_over_time"]["buckets"])
        if len(df) > 0:
            # anomaly_predicted_count == 2 for 'Anomaly' labeled log messages
            df["doc_count"] = df["doc_count"] // 2
            for index, row in df.iterrows():
                timestamp, anomaly_count = row["key"], row["doc_count"]
                if pd_model.detect_peaks(anomaly_count):
                    peak_timestamps.append({"timestamp": timestamp})
        return peak_timestamps
    except Exception as e:
        logging.error("Unable to obtain peaks")
        return peak_timestamps


async def get_areas_of_interest(start_ts, end_ts):
    '''
    This function will fetch all areas of interest between the starting and ending timestamp. It will return a list
    of dictionary objects with a start_ts and end_ts of each of the overarching areas of interest and a list consisting
    of the smaller areas of interest that are present within this expanded time interval. The idea behind this
    is to reduce the immediate number of area of interest time intervals that are returned.
    '''
    logging.info(
        f"Received request to obtain all areas of interest between {start_ts} and {end_ts}"
    )

    query = {
        "query": {
            "bool": {
                "must": [{"match": {"anomaly_level.keyword": "Anomaly"}}],
                "filter": [{"range": {"timestamp": {"gte": start_ts, "lte": end_ts}}}],
            }
        },
        "aggs": {
            "logs_over_time": {
                "date_histogram": {"field": "timestamp", "calendar_interval": "minute"},
                "aggs": {"total_normal": {"sum": {"field": "anomaly_predicted_count"}}},
            }
        },
    }
    try:
        res = await es_instance.search(index="logs", body=query, size=0)
        df = pd.DataFrame(res["aggregations"]["logs_over_time"]["buckets"])
        areas_of_interest = []
        if len(df) > 0:
            # anomaly_predicted_count == 2 for 'Anomaly' labeled log messages
            df["doc_count"] = df["doc_count"] / 2
            df["moving_avg"] = df["doc_count"].rolling(60).mean() * 1.3
            df["AOI"] = df.doc_count.gt(df.moving_avg.shift())
            areas_of_interest_df = df[df.AOI == True]
            areas_of_interest_df["time_diff"] = areas_of_interest_df["key"].diff()
            current_aoi_start = -1
            prev_segment_start = -1
            aoi_start_ts = -1
            current_interval_areas = []
            '''
            Iterate over the areas of interest found and create a larger area of interest time interval which will contain
            time intervals which are within 10 minutes of the previous area of interest time interval. This reduces
            the outward number of areas of interest time intervals returned.
            '''
            for index, row in areas_of_interest_df.iterrows():
                if current_aoi_start == -1:
                    current_aoi_start = row["key"]
                    aoi_start_ts = row["key"]
                if not pd.isna(row['time_diff']) and row["time_diff"] != MILLISECONDS_MINUTE:
                    '''
                    If the starting timestamp of the next area of interest (row["key"]) is AOI_MINUTES_THRESHOLD (default: 10)
                    minutes after the ending timestamp of the prior area of interest (prev_segment_start + MILLISECONDS_MINUTE)
                    then close that area of interest and add it to the areas_of_interest list and start a new list for
                    the next area of interest group. Otherwise, add that area of interest to the current_interval_areas
                    list.
                    '''
                    if row["key"] - prev_segment_start > ((AOI_MINUTES_THRESHOLD + 1) * MILLISECONDS_MINUTE):
                        current_interval_areas.append({"start_ts": current_aoi_start, "end_ts": prev_segment_start + MILLISECONDS_MINUTE})
                        areas_of_interest.append({"start_ts": aoi_start_ts, "end_ts": prev_segment_start + MILLISECONDS_MINUTE,
                                                 "areas_of_interest": current_interval_areas})
                        aoi_start_ts = row["key"]
                        current_interval_areas = []
                    else:
                        current_interval_areas.append({"start_ts": current_aoi_start, "end_ts": prev_segment_start + MILLISECONDS_MINUTE})
                    current_aoi_start = row["key"]
                prev_segment_start = row["key"]

                if index == len(areas_of_interest_df) - 1:
                    current_interval_areas.append({"start_ts": current_aoi_start, "end_ts": prev_segment_start + MILLISECONDS_MINUTE})
                    areas_of_interest.append({"start_ts": aoi_start_ts, "end_ts": prev_segment_start + MILLISECONDS_MINUTE,
                                             "areas_of_interest": current_interval_areas})
        return areas_of_interest
    except Exception as e:
        logging.error("Unable to retrieve areas of interest.")
        return areas_of_interest

async def get_namespace_breakdown(start_ts, end_ts):
    # Get the breakdown of normal, suspicious and anomalous logs by namespace.
    namespace_breakdown_dict = {"Namespaces": []}

    query_body = {
        "size": 0,
        "query": {
            "bool": {
                "must": [{"match": {"is_control_plane_log": "false"}}, {"regexp": {"kubernetes.namespace_name": ".+"}}],
                "filter": [{"range": {"timestamp": {"gte": start_ts, "lte": end_ts}}}],
            }
        },
        "aggs": {
            "bucket": {
                "composite": {
                    "size": 1000,
                    "sources": [{"namespace_name": {"terms": {"field":"kubernetes.namespace_name.keyword"}}}, {"anomaly_level": {"terms": {"field": "anomaly_level.keyword"}}}],
                }
            }
        }
    }
    namespace_aggregation_dict = dict()
    try:
        namespace_aggregation_results = await get_aggregated_data(query_body)
        for batch in namespace_aggregation_results:
            for each_result in batch:
                namespace_name, anomaly_level = each_result["key"]["namespace_name"], each_result["key"]["anomaly_level"]
                if not namespace_name in namespace_aggregation_dict:
                    namespace_aggregation_dict[namespace_name] = {"Normal": 0, "Suspicious": 0, "Anomaly": 0}
                namespace_aggregation_dict[namespace_name][anomaly_level] = each_result["doc_count"]

        for namespace in namespace_aggregation_dict:
            individual_namespace_dict = {
                "Name": namespace,
                "Insights": namespace_aggregation_dict[namespace]
            }
            namespace_breakdown_dict["Namespaces"].append(individual_namespace_dict)
    except Exception as e:
        logging.error(f"Unable to access Elasticsearch data. {e}")
        return namespace_breakdown_dict
    return namespace_breakdown_dict

async def get_control_plane_components_breakdown(start_ts, end_ts):
    # Get the breakdown of normal, suspicious and anomolous logs by kubernetes control plane component.
    kubernetes_components_breakdown_dict = {"Components": []}
    kubernetes_components_storage_dict = dict()

    kubernetes_components = [
        "kubelet",
        "kube-controller-manager",
        "kube-apiserver",
        "kube-proxy",
        "kube-scheduler",
        "etcd",
        "k3s-agent",
        "k3s-server",
        "rke2-agent",
        "rke2-server",
    ]
    for component in kubernetes_components:
        kubernetes_components_storage_dict[component] = {
            "Insights": {"Normal": 0, "Suspicious": 0, "Anomaly": 0}
        }

    query_body = {
        "size": 0,
        "query": {
            "bool": {
                "filter": [{"range": {"timestamp": {"gte": start_ts, "lte": end_ts}}}],
                "must": [{"match": {"is_control_plane_log": "true"}}],
            }
        },
        "aggs": {
            "component_name": {
                "terms": {"field": "kubernetes_component.keyword"},
                "aggs": {
                    "anomaly_level": {"terms": {"field": "anomaly_level.keyword"}}
                },
            }
        },
    }

    try:
        component_level_buckets = (
            await es_instance.search(index="logs", body=query_body)
        )["aggregations"]["component_name"]["buckets"]
        for each_component_bucket in component_level_buckets:
            anomaly_level_buckets = each_component_bucket["anomaly_level"]["buckets"]
            for bucket in anomaly_level_buckets:
                kubernetes_components_storage_dict[each_component_bucket["key"]][
                    "Insights"
                ][bucket["key"]] = bucket["doc_count"]

        for component_name in kubernetes_components_storage_dict:
            kubernetes_components_breakdown_dict["Components"].append(
                {
                    "Name": component_name,
                    "Insights": kubernetes_components_storage_dict[component_name]["Insights"],
                }
            )

    except Exception as e:
        logging.error(f"Unable to access Elasticsearch data. {e}")
        return kubernetes_components_breakdown_dict

    return kubernetes_components_breakdown_dict
