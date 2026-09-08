packages <- c(MatchIt='4.7.2', cobalt='5.0.0', logistf='1.26.1', survival='3.5.3', jsonlite='1.8.4')
if (file.exists('r-library-path.txt')) .libPaths(c(readLines('r-library-path.txt'), .libPaths()))
for (p in names(packages)) {
  stopifnot(requireNamespace(p, quietly=TRUE))
  actual <- as.character(packageVersion(p))
  if (actual != packages[[p]]) stop(paste('Version mismatch for', p, ':', actual, 'expected', packages[[p]]))
  cat(p, actual, '\n')
}
