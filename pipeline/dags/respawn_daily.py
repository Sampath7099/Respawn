"""Daily Respawn pipeline: load raw data -> simulate traffic -> dbt build (models + tests).

dbt tests are the data-quality gate: if any test fails the task fails and the
alert callback fires, so broken data never silently reaches the dashboard.
"""
from datetime import datetime, timedelta
import logging

from airflow import DAG
from airflow.operators.bash import BashOperator

DBT = "dbt {cmd} --project-dir /opt/respawn/pipeline/dbt --profiles-dir /opt/respawn/pipeline/dbt"


def alert(context):
    ti = context["task_instance"]
    # swap for a Slack/email webhook in production
    logging.error("DATA ALERT: %s.%s failed on %s", ti.dag_id, ti.task_id, context["ds"])


with DAG(
    dag_id="respawn_daily",
    start_date=datetime(2026, 6, 1),
    schedule="@daily",
    catchup=False,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=2), "on_failure_callback": alert},
    tags=["respawn"],
) as dag:
    ingest = BashOperator(task_id="ingest_raw",
                          bash_command="python /opt/respawn/pipeline/ingest.py")
    simulate = BashOperator(task_id="simulate_traffic",
                            bash_command="python /opt/respawn/simulator/simulate.py")
    freshness = BashOperator(task_id="source_freshness", bash_command=DBT.format(cmd="source freshness"))
    build = BashOperator(task_id="dbt_build_and_test", bash_command=DBT.format(cmd="build"))

    ingest >> simulate >> freshness >> build
