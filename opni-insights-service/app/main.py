# Standard Library
import asyncio
import logging
from typing import Optional

# Third Party
from endpoint_functions import *
from fastapi import FastAPI

app = FastAPI()
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(message)s")
workload_monitoring = BackgroundFunction()

@app.get("/insights_breakdown")
async def index_breakdown(start_ts: int, end_ts: int):
    # This function handles get requests for fetching pod,namespace and workload breakdown insights.
    logging.info(
        f"Received request to obtain pod insights between {start_ts} and {end_ts}"
    )
    try:
        pod_breakdown_dict, workload_breakdown_dict = await get_pod_aggregation(
            start_ts, end_ts
        )
        namespace_breakdown_dict = await get_namespace_breakdown(start_ts, end_ts)
        control_plane_breakdown_dict = await get_control_plane_components_breakdown(start_ts, end_ts)

        return {
            "Pods": pod_breakdown_dict["Pods"],
            "Workloads": workload_breakdown_dict,
            "Namespaces": namespace_breakdown_dict["Namespaces"],
            "Control Plane": control_plane_breakdown_dict
        }
    except Exception as e:
        # Bad Request
        logging.error(e)


@app.get("/overall_insights")
async def index_overall_breakdown(start_ts: int, end_ts: int, granularity_level: str):
    # This function handles get requests for fetching overall insights between the start_ts and end_ts and a specified granularity time level.
    logging.info(
        f"Received request to obtain all insights between {start_ts} and {end_ts}"
    )
    try:
        result = await get_overall_breakdown(start_ts, end_ts, granularity_level)
        return result
    except Exception as e:
        # Bad Request
        logging.error(e)

@app.get("/anomalies_breakdown")
async def index_anomalies_breakdown(start_ts: int, end_ts: int):
    # This function handles get requests for fetching the number of anomalies between control plane and workload logs between the start_ts and end_ts.
    logging.info(
        f"Received request to obtain all insights between {start_ts} and {end_ts}"
    )
    try:
        result = await get_anomalies_breakdown(start_ts, end_ts)
        return result
    except Exception as e:
        # Bad Request
        logging.error(e)


@app.get("/logs_pod")
async def index_logs_pod(start_ts: int, end_ts: int, anomaly_level: str, pod_name: str, namespace_name: str, scroll_id: Optional[str] = None):
    # This function handles get requests for fetching logs for a particular pod within a specific namespace with a specified anomaly level between start_ts and end_ts and a scroll_id which is an optional parameter.
    logging.info(
        f"Received request to obtain logs between {start_ts} and {end_ts} for the pod {pod_name} which is in the {namespace_name} namespace which were marked as {anomaly_level}"
    )
    try:
        query_parameters = {"anomaly_level": anomaly_level,"type": "pod", "pod_name": pod_name, "namespace_name": namespace_name}
        result = await get_logs(start_ts, end_ts, query_parameters, scroll_id)
        return result
    except Exception as e:
        # Bad Request
        logging.error(e)

@app.get("/logs_namespace")
async def index_logs_namespace(start_ts: int, end_ts: int, anomaly_level: str, namespace_name: str, scroll_id: Optional[str] = None):
    # This function handles get requests for fetching logs for a particular namespace name with a specified anomaly level between start_ts and end_ts and a scroll_id which is an optional parameter.
    logging.info(
        f"Received request to obtain logs between {start_ts} and {end_ts} within {namespace_name} namespace which were marked as {anomaly_level}"
    )
    try:
        query_parameters = {"anomaly_level": anomaly_level,"type": "namespace", "namespace_name": namespace_name}
        result = await get_logs(start_ts, end_ts, query_parameters, scroll_id)
        return result
    except Exception as e:
        # Bad Request
        logging.error(e)

@app.get("/logs_workload")
async def index_logs_workload(start_ts: int, end_ts: int, anomaly_level: str, namespace_name: str, workload_type: str, workload_name: str, scroll_id: Optional[str] = None):
    # This function handles get requests for fetching logs for a particular workload within a specified namespace with a specified anomaly level between start_ts and end_ts and a scroll_id which is an optional parameter.
    logging.info(
        f"Received request to obtain logs between {start_ts} and {end_ts} for the workload {workload_name} which is in the {namespace_name} namespace which were marked as {anomaly_level}"
    )
    try:
        query_parameters = {"anomaly_level": anomaly_level,"type": "workload", "namespace_name": namespace_name, "workload_type": workload_type, "workload_name": workload_name}
        result = await get_logs(start_ts, end_ts, query_parameters, scroll_id)
        return result
    except Exception as e:
        # Bad Request
        logging.error(e)

@app.get("/logs_control_plane")
async def index_logs_control_plane(start_ts: int, end_ts: int, anomaly_level: str,control_plane_component: str, scroll_id: Optional[str] = None):
    # This function handles get requests for fetching logs for a specified control_plane_component with a specified anomaly level between start_ts and end_ts and a scroll_id which is an optional parameter.
    logging.info(
        f"Received request to obtain all suspicious and anomalous logs between {start_ts} and {end_ts}"
    )
    try:
        query_parameters = {"anomaly_level": anomaly_level,"type": "control_plane", "control_plane_component": control_plane_component}
        result = await get_logs(start_ts, end_ts, query_parameters, scroll_id)
        return result
    except Exception as e:
        # Bad Request
        logging.error(e)

@app.get("/areas_of_interest")
async def index_areas_of_interest(start_ts: int, end_ts: int):
    # This function handles get requests for fetching areas of interest between start_ts and end_ts.
    logging.info(
        f"Received request to obtain all areas of interest between {start_ts} and {end_ts}"
    )
    try:
        result = await get_areas_of_interest(start_ts, end_ts)
        return result
    except Exception as e:
        # Bad Request
        logging.error(e)

@app.get("/peaks")
async def index_peaks(start_ts: int, end_ts: int):
    # This function handles get requests for fetching peaks between start_ts and end_ts.
    logging.info(
        f"Received request to obtain all anomalous peaks between {start_ts} and {end_ts}"
    )
    try:
        result = await get_peaks(start_ts, end_ts)
        return result
    except Exception as e:
        # Bad Request
        logging.error(e)

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(workload_monitoring.monitor_workloads())
