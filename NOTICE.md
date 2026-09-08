# Dependency credits

This project calls established packages instead of copying their matching optimizers or regression solvers. Each dependency retains its own copyright and license; the MIT license for this repository does not relicense them. Installed distributions include their license files. No third-party package source is vendored in this repository.

| Package | Role | Primary project reference |
|---|---|---|
| MatchIt | Matching | https://kosukeimai.github.io/MatchIt/ |
| cobalt | Balance diagnostics | https://ngreifer.github.io/cobalt/ |
| logistf | Firth logistic regression and profile likelihood | https://cran.r-project.org/package=logistf |
| survival | Independent conditional-logistic test reference | https://cran.r-project.org/package=survival |
| statsmodels | Conditional logistic regression and Holm adjustment | https://www.statsmodels.org/ |
| pandas / NumPy / SciPy | Tabular and numerical operations | https://pandas.pydata.org/ / https://numpy.org/ / https://scipy.org/ |
| Pydantic / PyYAML | Configuration validation and loading | https://docs.pydantic.dev/ / https://pyyaml.org/ |
| google-cloud-bigquery / db-dtypes / PyArrow | Authorized BigQuery access and typed storage | https://cloud.google.com/python/docs/reference/bigquery/latest / https://arrow.apache.org/ |
| renv | R dependency restoration | https://rstudio.github.io/renv/ |

For manuscript references, obtain the exact installed R citations with `citation("MatchIt")`, `citation("cobalt")`, `citation("logistf")`, and `citation("survival")`. Use the corresponding Python project citation guidance. Record versions and the exact library commit used; do not cite a moving branch as a reproducible release.
