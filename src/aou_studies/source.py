"""All of Us v9 OMOP extraction through the official BigQuery client.

Only run real-data extraction inside the authorized Workbench. Test clients can
be injected without credentials. No cb_/ds_ operational tables are used.
"""

from __future__ import annotations

from datetime import timedelta
from dataclasses import replace
import re
import pandas as pd
from google.cloud import bigquery

from .context import WorkspaceContext
from .specs import StudySpec, ConceptSet
from .specs import SurveyFeature
from .errors import DataContractError, ContextError
from .features import age_on, reduce_survey, reduce_measurement
from .contracts import unique_people
from .provenance import digest

REQUIRED_SCHEMA = {
    "person": {
        "person_id",
        "birth_datetime",
        "sex_at_birth_concept_id",
        "race_concept_id",
        "ethnicity_concept_id",
    },
    "condition_occurrence": {"person_id", "condition_concept_id", "condition_start_date"},
    "visit_occurrence": {"person_id", "visit_start_date"},
    "concept": {
        "concept_id",
        "concept_name",
        "domain_id",
        "vocabulary_id",
        "concept_code",
        "standard_concept",
        "invalid_reason",
    },
    "concept_ancestor": {"ancestor_concept_id", "descendant_concept_id"},
    "observation": {
        "person_id",
        "observation_date",
        "observation_source_concept_id",
        "value_source_concept_id",
        "value_as_number",
        "value_as_string",
    },
    "measurement": {
        "person_id",
        "measurement_concept_id",
        "measurement_date",
        "value_as_number",
        "unit_concept_id",
    },
}


def parameter(name, kind, value):
    return bigquery.ScalarQueryParameter(name, kind, value)


class BigQuerySource:
    def __init__(self, context: WorkspaceContext, *, maximum_bytes_billed: int = 10_000_000_000, client=None):
        if maximum_bytes_billed <= 0:
            raise ValueError("Set a positive per-query maximum_bytes_billed.")
        self.context = context
        self.client = client if client is not None else bigquery.Client(project=context.billing_project)
        self.maximum_bytes_billed = maximum_bytes_billed
        self.jobs: list[dict] = []
        self.resolved_concepts: dict[str, dict] = {}
        self.resolved_surveys: dict[str, SurveyFeature] = {}
        self.survey_metadata: dict = {}
        self.schema: dict = {}
        self._preflighted = False
        self._prepared_hash = None
        self._last_destination = None

    def table(self, name):
        if name not in REQUIRED_SCHEMA:
            raise ValueError("Table not in the supported OMOP extraction contract.")
        return f"`{self.context.dataset}.{name}`"

    def preflight(self, study: StudySpec) -> dict:
        self._preflighted = False
        self.context.require_release(pinned=study.dataset, cutoff=study.clinical_cutoff)
        if study.tier != self.context.tier:
            raise ContextError("Study tier and resolved dataset tier disagree.")
        metadata = self.client.get_dataset(self.context.dataset)
        actual_location = metadata.location
        if self.context.location and self.context.location.lower() != actual_location.lower():
            raise ContextError("Configured query location differs from the source dataset location.")
        self.context = replace(self.context, location=actual_location)
        tables = set(REQUIRED_SCHEMA) - {"observation", "measurement"}
        if study.surveys:
            tables.add("observation")
        if study.measurements:
            tables.add("measurement")
        for table in sorted(tables):
            meta = self.client.get_table(f"{self.context.dataset}.{table}")
            columns = {field.name: field.field_type for field in meta.schema}
            missing = REQUIRED_SCHEMA[table] - columns.keys()
            if missing:
                raise DataContractError(f"{table} is missing required documented fields: {sorted(missing)}")
            for col in REQUIRED_SCHEMA[table]:
                allowed = (
                    {"DATE", "DATETIME", "TIMESTAMP"}
                    if col.endswith(("_date", "_datetime"))
                    else {"INTEGER", "INT64"}
                    if col.endswith("_id") and col not in {"domain_id", "vocabulary_id"}
                    else {"FLOAT", "FLOAT64", "NUMERIC", "BIGNUMERIC", "INTEGER", "INT64"}
                    if col == "value_as_number"
                    else {"STRING"}
                )
                if columns[col] not in allowed:
                    raise DataContractError(f"Unexpected schema type for {table}.{col}: {columns[col]}")
            self.schema[table] = {k: columns[k] for k in sorted(REQUIRED_SCHEMA[table])}
        self._preflighted = True
        return {"context": self.context.summary(), "schema": self.schema, "schema_hash": digest(self.schema)}

    def query(self, sql, parameters=(), *, dry_run=False):
        if not self._preflighted:
            raise ContextError("Run source.preflight(study) before queries.")
        config = bigquery.QueryJobConfig(
            query_parameters=list(parameters),
            dry_run=dry_run,
            use_query_cache=not dry_run,
            maximum_bytes_billed=self.maximum_bytes_billed,
            labels={"library": "aou-studies"},
        )
        job = self.client.query(sql, job_config=config, location=self.context.location)
        record = {
            "sql_hash": digest(sql),
            "parameters_hash": digest([p.to_api_repr() for p in parameters]),
            "dry_run": dry_run,
            "job_id": job.job_id,
        }
        if dry_run:
            record["bytes_estimated"] = job.total_bytes_processed
            self.jobs.append(record)
            if job.total_bytes_processed and job.total_bytes_processed > self.maximum_bytes_billed:
                raise DataContractError(
                    "Query estimate exceeds maximum_bytes_billed; revise scope or explicit cap."
                )
            return record
        rows = job.result()
        self._last_destination = getattr(job, "destination", None)
        result = rows.to_dataframe(create_bqstorage_client=False)
        record.update(bytes_processed=job.total_bytes_processed, cache_hit=job.cache_hit)
        self.jobs.append(record)
        return result

    def resolve_concepts(self, definition: ConceptSet) -> dict:
        params = [
            bigquery.ArrayQueryParameter("ids", "INT64", definition.ids),
            bigquery.ArrayQueryParameter("codes", "STRING", definition.codes),
            parameter("vocabulary", "STRING", definition.vocabulary),
        ]
        sql = f"""SELECT concept_id, concept_name, domain_id, vocabulary_id, concept_code,
                         standard_concept, invalid_reason FROM {self.table("concept")}
                  WHERE concept_id IN UNNEST(@ids) OR
                    (vocabulary_id=@vocabulary AND concept_code IN UNNEST(@codes))"""
        seeds = self.query(sql, params)
        if not set(definition.ids).issubset(set(seeds.concept_id)):
            raise DataContractError("One or more seed concept IDs are absent from this release.")
        found_codes = set(seeds.loc[seeds.vocabulary_id == definition.vocabulary, "concept_code"])
        if not set(definition.codes).issubset(found_codes):
            raise DataContractError("One or more vocabulary codes are absent from this release.")
        if seeds.empty or (seeds.domain_id != definition.domain).any() or seeds.invalid_reason.notna().any():
            raise DataContractError("Seed concepts are empty, invalid, or in the wrong domain.")
        if definition.require_standard and (seeds.standard_concept != "S").any():
            raise DataContractError("Nonstandard seed: provide an explicitly reviewed standard mapping.")
        ids = sorted(set(int(v) for v in seeds.concept_id))
        resolved = seeds
        if definition.descendants:
            sql = f"""SELECT DISTINCT c.concept_id, c.concept_name, c.domain_id, c.vocabulary_id,
                            c.concept_code, c.standard_concept, c.invalid_reason
                     FROM {self.table("concept")} c WHERE c.concept_id IN
                       (SELECT descendant_concept_id FROM {self.table("concept_ancestor")}
                        WHERE ancestor_concept_id IN UNNEST(@seeds))
                     OR c.concept_id IN UNNEST(@seeds)"""
            resolved = self.query(sql, [bigquery.ArrayQueryParameter("seeds", "INT64", ids)])
        resolved = resolved[
            (resolved.domain_id == definition.domain)
            & resolved.invalid_reason.isna()
            & ~resolved.concept_id.isin(definition.exclude_ids)
        ]
        if definition.require_standard:
            resolved = resolved[resolved.standard_concept == "S"]
        if resolved.empty:
            raise DataContractError("Resolved concept set is empty after restrictions.")
        records = resolved.sort_values("concept_id").to_dict("records")
        return {
            "ids": sorted(int(v) for v in resolved.concept_id.unique()),
            "records": records,
            "definition": definition.model_dump(mode="json"),
            "hash": digest(records),
        }

    def prepare(self, study: StudySpec) -> dict:
        """Preflight and resolve vocabulary metadata only; no participant data is returned."""
        info = self.preflight(study)
        self.resolved_concepts = {}
        self.resolved_surveys = {}
        self.survey_metadata = {}
        concept_cache = {}
        for name, feature in {**study.conditions, **study.measurements}.items():
            key = digest(feature.concepts.model_dump(mode="json"))
            if key not in concept_cache:
                concept_cache[key] = self.resolve_concepts(feature.concepts)
            self.resolved_concepts[name] = concept_cache[key]
        for name, feature in study.surveys.items():
            self.resolved_surveys[name], self.survey_metadata[name] = self.resolve_survey(feature)
        units = {}
        for name, feature in study.measurements.items():
            sql = f"""SELECT concept_id, concept_code FROM {self.table("concept")}
                      WHERE vocabulary_id=@vocabulary AND concept_code IN UNNEST(@codes)
                        AND invalid_reason IS NULL"""
            resolved = self.query(
                sql,
                [
                    parameter("vocabulary", "STRING", feature.unit_vocabulary),
                    bigquery.ArrayQueryParameter("codes", "STRING", feature.unit_codes),
                ],
            )
            if set(resolved.concept_code) != set(feature.unit_codes):
                raise DataContractError(f"Measurement {name} has an unrecognized unit code in this release.")
            units[name] = resolved.sort_values("concept_id").to_dict("records")
        self._prepared_hash = digest(study.model_dump(mode="json"))
        return {**info, "concepts": self.resolved_concepts, "surveys": self.survey_metadata, "units": units}

    def resolve_survey(self, spec: SurveyFeature):
        codes = set(spec.positive_codes) | set(spec.negative_codes) | set(spec.numeric_positive_codes)
        ids = set(spec.positive) | set(spec.negative) | set(spec.numeric_positive_above)
        for answers in [*spec.positive_codes.values(), *spec.negative_codes.values()]:
            codes.update(answers)
        for answers in [*spec.positive.values(), *spec.negative.values()]:
            ids.update(answers)
        sql = f"""SELECT concept_id, concept_code, concept_name, vocabulary_id, invalid_reason
                  FROM {self.table("concept")}
                  WHERE concept_id IN UNNEST(@ids) OR
                    (vocabulary_id=@vocabulary AND LOWER(concept_code) IN UNNEST(@codes))"""
        records = self.query(
            sql,
            [
                bigquery.ArrayQueryParameter("ids", "INT64", sorted(ids)),
                bigquery.ArrayQueryParameter("codes", "STRING", sorted(c.lower() for c in codes)),
                parameter("vocabulary", "STRING", spec.vocabulary),
            ],
        )
        if not ids.issubset(set(records.concept_id)) or records.invalid_reason.notna().any():
            raise DataContractError("Survey concepts are missing or invalid in the selected vocabulary.")
        by_code = records.loc[records.vocabulary_id.eq(spec.vocabulary)].copy()
        by_code["normalized"] = by_code.concept_code.str.lower()
        if by_code.normalized.duplicated().any() or not {c.lower() for c in codes}.issubset(
            set(by_code.normalized)
        ):
            raise DataContractError(
                "Survey source codes are missing or ambiguous; review the release codebook."
            )
        lookup = dict(zip(by_code.normalized, by_code.concept_id.astype(int)))
        values = spec.model_dump(mode="python")
        for target, source in [("positive", "positive_codes"), ("negative", "negative_codes")]:
            mapping = dict(values[target])
            for question, answers in values[source].items():
                q = lookup[question.lower()]
                mapping[q] = tuple(sorted(set(mapping.get(q, ())) | {lookup[a.lower()] for a in answers}))
            values[target] = mapping
            values[source] = {}
        for question, threshold in spec.numeric_positive_codes.items():
            values["numeric_positive_above"][lookup[question.lower()]] = threshold
        values["numeric_positive_codes"] = {}
        resolved = SurveyFeature.model_validate(values)
        metadata = {
            "rules": resolved.model_dump(mode="json"),
            "records": records.sort_values("concept_id").to_dict("records"),
        }
        return resolved, metadata

    def _population_cte(self, study):
        # Standard visit/condition evidence; no cohort-builder 'has EHR' flag assumptions.
        return f"""ehr_events AS (
          SELECT person_id, condition_start_date AS event_date FROM {self.table("condition_occurrence")}
          WHERE condition_start_date <= @cutoff
          UNION ALL SELECT person_id, visit_start_date FROM {self.table("visit_occurrence")}
          WHERE visit_start_date <= @cutoff
        ), ehr AS (
          SELECT person_id, COUNT(*) AS ehr_record_count,
                 DATE_DIFF(MAX(event_date), MIN(event_date), DAY) AS ehr_days
          FROM ehr_events GROUP BY person_id
        ), population AS (
          SELECT p.person_id, DATE(p.birth_datetime) AS birth_date,
                 p.sex_at_birth_concept_id, p.race_concept_id, p.ethnicity_concept_id,
                 ehr.ehr_record_count, ehr.ehr_days
          FROM {self.table("person")} p INNER JOIN ehr USING(person_id)
        )"""

    def extraction_query(self, study: StudySpec):
        if not set(study.conditions).issubset(self.resolved_concepts):
            raise ContextError("Call source.prepare(study) to resolve condition concepts first.")
        params = [parameter("cutoff", "DATE", study.clinical_cutoff)]
        fields = []
        for name, spec in study.conditions.items():
            if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
                raise ValueError("Invalid feature identifier.")
            params.append(
                bigquery.ArrayQueryParameter(f"{name}_ids", "INT64", self.resolved_concepts[name]["ids"])
            )
            test = f"c.condition_concept_id IN UNNEST(@{name}_ids)"
            if spec.lookback_days is not None:
                params.append(
                    parameter(
                        f"{name}_start", "DATE", study.clinical_cutoff - timedelta(days=spec.lookback_days)
                    )
                )
                test += f" AND c.condition_start_date >= @{name}_start"
            fields += [
                f"COUNT(DISTINCT IF({test}, c.condition_start_date, NULL)) AS {name}__days",
                f"MIN(IF({test}, c.condition_start_date, NULL)) AS {name}__first",
                f"MAX(IF({test}, c.condition_start_date, NULL)) AS {name}__last",
            ]
        sql = f"""WITH {self._population_cte(study)}, condition_features AS (
          SELECT c.person_id, {", ".join(fields)} FROM {self.table("condition_occurrence")} c
          WHERE c.condition_start_date <= @cutoff GROUP BY c.person_id
        ) SELECT p.*, {", ".join("cf." + f.split(" AS ")[-1] for f in fields)},
            s.concept_name AS sex_at_birth, r.concept_name AS race, e.concept_name AS ethnicity
          FROM population p LEFT JOIN condition_features cf USING(person_id)
          LEFT JOIN {self.table("concept")} s ON s.concept_id=p.sex_at_birth_concept_id
          LEFT JOIN {self.table("concept")} r ON r.concept_id=p.race_concept_id
          LEFT JOIN {self.table("concept")} e ON e.concept_id=p.ethnicity_concept_id"""
        return sql, params

    def extract(self, study: StudySpec) -> pd.DataFrame:
        if self._prepared_hash != digest(study.model_dump(mode="json")):
            self.prepare(study)
        sql, params = self.extraction_query(study)
        self.query(sql, params, dry_run=True)
        data = unique_people(self.query(sql, params))
        # Reuse BigQuery's temporary result inside its authorized cloud project.
        # This prevents each survey/measurement feature from rescanning the EHR population.
        destination = self._last_destination
        population = (
            f"population AS (SELECT person_id FROM `{destination.project}.{destination.dataset_id}.{destination.table_id}`)"
            if destination is not None
            else self._population_cte(study)
        )
        data["age"] = age_on(data.birth_date, study.age_reference_date)
        data["age_at_cutoff"] = age_on(data.birth_date, study.clinical_cutoff)
        for name, spec in study.conditions.items():
            days = data[f"{name}__days"].fillna(0)
            span = (
                pd.to_datetime(data[f"{name}__last"]) - pd.to_datetime(data[f"{name}__first"])
            ).dt.days.fillna(0)
            data[f"{name}__span"] = span
            data[name] = ((days >= spec.min_distinct_dates) & (span >= spec.min_span_days)).astype(int)
        for name in ["sex_at_birth", "race", "ethnicity"]:
            data[name] = data[name].fillna("unknown")
        # Reduce source records server-side to the eligible date window and latest date per question.
        if study.surveys:
            questions = sorted(
                set().union(
                    *(
                        set(s.positive) | set(s.negative) | set(s.numeric_positive_above)
                        for s in self.resolved_surveys.values()
                    )
                )
            )
            sql = f"""WITH {population}
              SELECT CAST(o.person_id AS STRING) AS person_id,
                observation_source_concept_id AS question_id, value_source_concept_id AS answer_id,
                observation_date AS event_date, value_as_number, value_as_string
              FROM {self.table("observation")} o JOIN population p USING(person_id)
              WHERE observation_source_concept_id IN UNNEST(@questions) AND observation_date <= @cutoff
              QUALIFY observation_date=MAX(observation_date) OVER
                      (PARTITION BY o.person_id, observation_source_concept_id)"""
            params = [
                parameter("cutoff", "DATE", study.clinical_cutoff),
                bigquery.ArrayQueryParameter("questions", "INT64", questions),
            ]
            self.query(sql, params, dry_run=True)
            events = self.query(sql, params)
            for name, spec in self.resolved_surveys.items():
                reduced = reduce_survey(events, spec, study.clinical_cutoff).rename(columns={"value": name})
                data = data.merge(reduced, on="person_id", how="left", validate="one_to_one")
                data[name] = data[name].fillna(spec.unknown_label)
        for name, spec in study.measurements.items():
            sql = f"""WITH {population}
              SELECT CAST(m.person_id AS STRING) AS person_id, m.measurement_date AS event_date,
                     m.value_as_number AS value, u.concept_code AS unit_code
              FROM {self.table("measurement")} m JOIN population p USING(person_id)
              JOIN {self.table("concept")} u ON u.concept_id=m.unit_concept_id
              WHERE measurement_concept_id IN UNNEST(@ids)
                AND measurement_date BETWEEN @start AND @cutoff
                AND u.vocabulary_id=@unit_vocabulary AND u.concept_code IN UNNEST(@units)
                AND value_as_number BETWEEN @minimum AND @maximum
              QUALIFY measurement_date=MAX(measurement_date) OVER (PARTITION BY m.person_id)"""
            params = [
                parameter("cutoff", "DATE", study.clinical_cutoff),
                parameter("start", "DATE", study.clinical_cutoff - timedelta(days=spec.lookback_days)),
                bigquery.ArrayQueryParameter("ids", "INT64", self.resolved_concepts[name]["ids"]),
                bigquery.ArrayQueryParameter("units", "STRING", spec.unit_codes),
                parameter("unit_vocabulary", "STRING", spec.unit_vocabulary),
                parameter("minimum", "FLOAT64", spec.minimum),
                parameter("maximum", "FLOAT64", spec.maximum),
            ]
            self.query(sql, params, dry_run=True)
            reduced = reduce_measurement(self.query(sql, params), spec, study.clinical_cutoff).rename(
                columns={"value": name}
            )
            data = data.merge(reduced, on="person_id", how="left", validate="one_to_one")
        return unique_people(data)
