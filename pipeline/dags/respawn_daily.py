"""Respawn pipelines.

respawn_daily      (@daily)  live-traffic freshness check -> dbt build (models + tests).
                             New live events arrive continuously through Kafka; this
                             rebuilds the marts on top of them. A failed dbt test fails
                             the run and fires the alert callback.
respawn_bootstrap  (manual)  one-off setup: load the static dataset (skipped if already
                             loaded) -> simulate history -> dbt build. Training the model
                             (recsys/train.py, needs torch) is a separate, offline step.
"""
import logging
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.bash import BashOperator

DBT = "dbt {cmd} --project-dir /opt/respawn/pipeline/dbt --profiles-dir /opt/respawn/pipeline/dbt"


def alert(context):
    ti = context["task_instance"]
    # swap for a Slack/email webhook in production
    logging.error("DATA ALERT: %s.%s failed on %s", ti.dag_id, ti.task_id, context["ds"])


defaults = {"retries": 1, "retry_delay": timedelta(minutes=2), "on_failure_callback": alert}

with DAG(dag_id="respawn_daily", start_date=datetime(2026, 6, 1), schedule="@daily",
         catchup=False, default_args=defaults, tags=["respawn"]):
    freshness = BashOperator(task_id="live_events_freshness", bash_command=DBT.format(cmd="source freshness"))
    build = BashOperator(task_id="dbt_build_and_test", bash_command=DBT.format(cmd="build"))
    freshness >> build

with DAG(dag_id="respawn_bootstrap", start_date=datetime(2026, 6, 1), schedule=None,
         catchup=False, default_args=defaults, tags=["respawn"]):
    ingest = BashOperator(task_id="ingest_dataset",
                          bash_command="python /opt/respawn/pipeline/ingest.py --if-empty")
    simulate = BashOperator(task_id="simulate_history",
                            bash_command="python /opt/respawn/simulator/simulate.py")
    build = BashOperator(task_id="dbt_build_and_test", bash_command=DBT.format(cmd="build"))
    ingest >> simulate >> build
