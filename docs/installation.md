# Installation

Python 3.12 and R are required by the locked environment. The release is validated with Python 3.12 and R 4.2.2. Use a separate Python environment and R library so existing notebooks keep their dependencies.

## Local synthetic development

The development image contains the numerical libraries and compilers needed by MatchIt and logistf:

```sh
docker build -f Dockerfile.dev -t aou-studies-dev .
docker run --rm -v "$PWD:/workspace" -w /workspace aou-studies-dev sh -c 'pip install --no-deps -e . && pytest -q'
```

Only mount this public code repository. Do not mount research outputs or credentials for synthetic tests.

## Workbench

Use the public release commit recorded in the release asset `release-manifest.json`; tags alone can be moved. Clone inside the authorized VM and check out that commit. Install with the VM's Python 3.12 into a dedicated venv:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements.lock
.venv/bin/python -m pip install --no-deps .
.venv/bin/python -m ipykernel install --user --name aou-studies --display-name 'All of Us studies'
Rscript scripts/restore-r.R
```

Select the **All of Us studies** kernel. The setup cell reads `r-library-path.txt`, which points to the isolated R library restored from `renv.lock`. To use an existing compatible installation, verify it with `Rscript scripts/check-r.R`; the engine preflight reports any version difference.

Building R packages from source needs a C/C++/Fortran toolchain, BLAS/LAPACK headers and common R development headers. In Debian-based development environments these include `r-base-dev`, `libblas-dev` and `liblapack-dev`; see the Dockerfile. Do not assume that `install.packages()` returning zero means every package installed: always run the explicit engine/version check.

Real participant data, temporary CSVs passed to R, parquet caches and run manifests must remain inside the authorized Workbench filesystem. Public GitHub contains code and generated synthetic examples only. No cloud credentials are needed by CI.

The Python lock records the environment used in validation. The R lock records the engines and dependency closure. A different R major/minor version or updated numerical dependency needs the reference tests again and a new run environment identity.

If the VM's `python3` is older than 3.12, do not run the lockfile installation against it. First provide a Python 3.12 interpreter in that VM using its supported environment manager, then create the dedicated kernel. The exact locked NumPy and SciPy versions require Python 3.12. Successful installation under a different numerical environment is not evidence of agreement with the tested release.
