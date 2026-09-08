# Run from the cloned release root; restore into an isolated library.
options(repos=c(CRAN='https://cloud.r-project.org'))
if (!requireNamespace('renv', quietly=TRUE) || as.character(packageVersion('renv')) != '1.2.4') {
  for (url in c('https://cloud.r-project.org/src/contrib/renv_1.2.4.tar.gz',
                'https://cloud.r-project.org/src/contrib/Archive/renv/renv_1.2.4.tar.gz')) {
    try(install.packages(url, repos=NULL, type='source'), silent=TRUE)
    if (requireNamespace('renv', quietly=TRUE) && as.character(packageVersion('renv')) == '1.2.4') break
  }
}
stopifnot(requireNamespace('renv', quietly=TRUE), as.character(packageVersion('renv')) == '1.2.4')
library_path <- normalizePath('r-library', mustWork=FALSE)
dir.create(library_path, recursive=TRUE, showWarnings=FALSE)
renv::restore(lockfile='renv.lock', library=library_path, prompt=FALSE)
writeLines(library_path, 'r-library-path.txt')
.libPaths(c(library_path, .libPaths()))
source('scripts/check-r.R')
