"""Fixed matched-case-control model specifications with explicit failures."""

import warnings
import numpy as np
import pandas as pd
from scipy.stats import norm
from statsmodels.discrete.conditional_models import ConditionalLogit
from statsmodels.base.model import LikelihoodModel
from statsmodels.stats.multitest import multipletests
from .backends.r import run_r
from .contracts import MatchResult, valid_model_sets
from .errors import DataContractError
from .features import predicate_mask
from .specs import ModelSpec


def _sample(members, model, predictor):
    frame = members.copy()
    original_rows, original_sets = len(frame), int(frame.match_set_id.nunique())
    if frame.person_id.duplicated().any():
        raise DataContractError(
            "Inference with reused controls is not supported by this model; choose no replacement."
        )
    if model.restriction:
        frame = frame[predicate_mask(frame, model.restriction)]
    restriction_removed = original_rows - len(frame)
    columns = [predictor, *model.covariates]
    if not set(columns).issubset(frame):
        raise DataContractError("One or more requested model columns are missing.")
    for col in set(columns) - set(model.categorical):
        values = pd.to_numeric(frame[col], errors="coerce")
        frame[col] = values.where(np.isfinite(values))
    frame, attrition = valid_model_sets(frame, columns)
    attrition.update(
        rows_before=original_rows,
        sets_before=original_sets,
        rows_removed=original_rows - len(frame),
        sets_removed=original_sets - int(frame.match_set_id.nunique()),
        rows_removed_by_restriction=restriction_removed,
    )
    return frame, columns, attrition


def fit_model(matched: MatchResult, model: ModelSpec, predictor: str) -> dict:
    frame, terms, attrition = _sample(matched.members, model, predictor)
    result = {
        "model": model.name,
        "predictor": predictor,
        "method": model.method,
        "formula": "is_case ~ " + " + ".join(terms),
        "primary": model.primary,
        "family": model.family,
        "status": "non_estimable",
        "odds_ratio": None,
        "ci_lower": None,
        "ci_upper": None,
        "p_value": None,
        "coefficient": None,
        "standard_error": None,
        **attrition,
    }
    if not frame[predictor].isin([0, 1]).all():
        raise DataContractError("The supported condition-association interface requires a binary predictor.")
    result["cases_analyzed"] = int(frame.is_case.eq(1).sum())
    result["controls_analyzed"] = int(frame.is_case.eq(0).sum())
    for role, label in [(1, "case"), (0, "control")]:
        result[f"{label}_with_condition"] = int((frame.is_case.eq(role) & frame[predictor].eq(1)).sum())
        result[f"{label}_without_condition"] = int((frame.is_case.eq(role) & frame[predictor].eq(0)).sum())
    if frame.empty or frame[predictor].nunique() < 2:
        return {**result, "reason": "empty_sample_or_constant_predictor"}
    result["discordant_sets"] = int((frame.groupby("match_set_id")[predictor].nunique() > 1).sum())
    if model.method == "firth":
        if any(frame[col].nunique() < 2 for col in model.categorical):
            return {**result, "reason": "constant_categorical_adjustment_term"}
        design = pd.get_dummies(frame[terms], columns=list(model.categorical), drop_first=True, dtype=float)
        design = np.column_stack([np.ones(len(frame)), design.to_numpy()])
        if np.linalg.matrix_rank(design) < design.shape[1]:
            return {**result, "reason": "rank_deficient_firth_design"}
        fit = run_r(
            frame[["person_id", "is_case", "match_set_id", *terms]],
            {
                "mode": "firth",
                "terms": terms,
                "categorical": list(model.categorical),
                "max_iterations": model.max_iterations,
            },
        )
        beta = fit["coefficients"].get(predictor)
        lower, upper = fit["lower"].get(predictor), fit["upper"].get(predictor)
        p = fit["p"].get(predictor)
        result.update(
            ci_method="profile_penalized_likelihood",
            test_method="penalized_likelihood_ratio",
            engine_version=fit["version"],
            engine_warning=fit["engine_warning"],
            engine_runtime=fit["runtime"],
        )
        if any(v is None or not np.isfinite(v) for v in [beta, lower, upper, p]):
            return {**result, "reason": "firth_interval_or_fit_failed"}
        # Report engine convergence; never turn a warning into a normal estimate.
        if fit["engine_warning"] or not fit["converged"]:
            return {
                **result,
                "reason": "firth_engine_warning_requires_review",
                "convergence": fit["convergence"],
            }
        if not np.isfinite(np.exp([beta, lower, upper])).all():
            return {**result, "reason": "unbounded_exponentiated_interval"}
        return {
            **result,
            "status": "estimated",
            "coefficient": beta,
            "odds_ratio": float(np.exp(beta)),
            "ci_lower": float(np.exp(lower)),
            "ci_upper": float(np.exp(upper)),
            "p_value": p,
            "convergence": fit["convergence"],
        }
    if result["discordant_sets"] == 0:
        return {**result, "reason": "no_within_set_predictor_information"}
    x = pd.get_dummies(
        frame[terms], columns=list(set(model.categorical) & set(terms)), drop_first=True, dtype=float
    )
    invariant = [col for col in x if frame.assign(_v=x[col]).groupby("match_set_id")._v.nunique().max() <= 1]
    result["conditioned_out_terms"] = invariant
    # Invariant exact-match terms contain no conditional information; record rather than silently select.
    x = x.drop(columns=invariant).astype(float)
    if predictor not in x:
        return {**result, "reason": "predictor_conditioned_out"}
    centered = x - x.groupby(frame.match_set_id).transform("mean")
    if np.linalg.matrix_rank(centered.to_numpy()) != x.shape[1]:
        return {**result, "reason": "rank_deficient_conditional_design"}
    try:
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            engine = ConditionalLogit(
                frame.is_case.astype(int).to_numpy(), x.to_numpy(), groups=frame.match_set_id.to_numpy()
            )
            # The pinned ConditionalLogit.fit wrapper drops solver kwargs.
            # Use the existing statsmodels likelihood fitter to retain gtol and convergence metadata.
            fit = LikelihoodModel.fit(
                engine, method="bfgs", maxiter=model.max_iterations, gtol=1e-8, disp=False
            )
        pos = list(x.columns).index(predictor)
        beta, se = float(fit.params[pos]), float(fit.bse[pos])
        score = float(np.max(np.abs(engine.score(fit.params))))
        information = -engine.hessian(fit.params)
        eig = np.linalg.eigvalsh(information)
        result.update(
            score_max=score,
            information_min_eigenvalue=float(eig.min()),
            warnings=[w.category.__name__ for w in captured],
            ci_method="wald_pointwise",
            test_method="wald",
            optimizer="statsmodels_bfgs",
            optimizer_gtol=1e-8,
            optimizer_converged=bool(fit.mle_retvals.get("converged", False)),
        )
        if (
            captured
            or not fit.mle_retvals.get("converged", False)
            or not np.isfinite([beta, se, score]).all()
            or se <= 0
            or score > 1e-3
            or eig.min() <= 1e-8
        ):
            return {**result, "reason": "unstable_or_nonconverged_conditional_fit"}
        low, high = beta - norm.ppf(0.975) * se, beta + norm.ppf(0.975) * se
        if not np.isfinite(np.exp([beta, low, high])).all():
            return {**result, "reason": "unbounded_exponentiated_interval"}
        return {
            **result,
            "status": "estimated",
            "coefficient": beta,
            "standard_error": se,
            "odds_ratio": float(np.exp(beta)),
            "ci_lower": float(np.exp(low)),
            "ci_upper": float(np.exp(high)),
            "p_value": float(2 * norm.sf(abs(beta / se))),
        }
    except (ValueError, np.linalg.LinAlgError, OverflowError) as exc:
        return {**result, "reason": "conditional_fit_failed", "exception_type": type(exc).__name__}


def fit_models(matched: MatchResult, models: tuple[ModelSpec, ...]) -> pd.DataFrame:
    rows = []
    for model in models:
        for predictor in model.predictors:
            rows.append(fit_model(matched, model, predictor))
    results = pd.DataFrame(rows)
    results["p_holm"] = np.nan
    for family, indices in results.loc[results.primary].groupby("family").groups.items():
        # Missing estimates occupy their predeclared place with conservative p=1.
        p = pd.to_numeric(results.loc[indices, "p_value"], errors="raise").astype(float).fillna(1)
        adjusted = multipletests(p, method="holm")[1]
        results.loc[indices, "p_holm"] = adjusted
        results.loc[indices, "family_size"] = len(indices)
        results.loc[results.index.isin(indices) & results.p_value.isna(), "p_holm"] = np.nan
    return results
