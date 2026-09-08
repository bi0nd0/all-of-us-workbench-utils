# Structured adapter to established R engines. No custom matching/statistical solver.
args <- commandArgs(trailingOnly=TRUE)
suppressPackageStartupMessages(library(jsonlite))
request <- fromJSON(args[1], simplifyVector=FALSE)
input <- read.csv(args[2], check.names=FALSE, colClasses=c(person_id="character"),
                  na.strings=c(""), stringsAsFactors=FALSE)
output <- args[3]
result <- tryCatch({
  mode <- request$mode
  if (mode == "match") {
    suppressPackageStartupMessages(library(MatchIt))
    suppressPackageStartupMessages(library(cobalt))
    s <- request$spec
    for (v in unique(c(unlist(s$exact), unlist(s$categorical)))) input[[v]] <- factor(input[[v]])
    rownames(input) <- input$person_id
    form <- reformulate(unlist(s$distance), response="is_case")
    exact <- if(length(s$exact)) reformulate(unlist(s$exact)) else NULL
    caliper <- unlist(s$calipers)
    if (length(caliper)==0) caliper <- NULL
    if (s$method == "propensity") {
      # Named raw-variable calipers plus an unnamed standardized logit propensity caliper.
      caliper <- c(unname(s$propensity_caliper), caliper)
      std.caliper <- c(TRUE, rep(FALSE, length(caliper)-1))
      distance <- "glm"
    } else {
      distance <- "mahalanobis"
      std.caliper <- FALSE
    }
    set.seed(s$seed)
    fit <- matchit(form, data=input, method="nearest", distance=distance,
                   link="linear.logit", exact=exact, caliper=caliper, std.caliper=std.caliper,
                   ratio=s$ratio, replace=s$replace, m.order="data")
    mm <- fit$match.matrix
    rows <- list()
    for (i in seq_len(nrow(mm))) {
      caseid <- rownames(mm)[i]
      controls <- as.character(mm[i, !is.na(mm[i, ])])
      if(length(controls) < s$minimum_controls) next
      setid <- paste0("set_", caseid)
      rows[[length(rows)+1]] <- data.frame(person_id=caseid, match_set_id=setid,
                                        is_case=1L, control_order=0L, weight=1)
      for(j in seq_along(controls)) rows[[length(rows)+1]] <- data.frame(
        person_id=controls[j], match_set_id=setid, is_case=0L, control_order=j,
        weight=1/length(controls))
    }
    if(length(rows)==0) stop("No sets meet minimum_controls.")
    members <- do.call(rbind, rows)
    # Calculate balance for the actual retained members, including partial-set policy.
    covariates <- unique(c(unlist(s$exact), unlist(s$distance), names(s$calipers)))
    constants <- covariates[vapply(input[,covariates,drop=FALSE], function(x) length(unique(x)) < 2, logical(1))]
    balance_variables <- setdiff(covariates, constants)
    totals <- tapply(members$weight, members$person_id, sum)
    matchweights <- unname(totals[input$person_id])
    matchweights[is.na(matchweights)] <- 0
    balance <- if(length(balance_variables)) bal.tab(x=input[, balance_variables, drop=FALSE], treat=input$is_case,
                       weights=matchweights, method="matching", s.d.denom="treated",
                       binary="std", un=TRUE, stats=c("m", "v"))$Balance else
                       data.frame(Type=character(), Diff.Un=numeric(), V.Ratio.Un=numeric(),
                                  Diff.Adj=numeric(), V.Ratio.Adj=numeric())
    balance$variable <- rownames(balance)
    if(length(constants)) {
      constant_rows <- as.data.frame(matrix(NA, nrow=length(constants), ncol=ncol(balance)))
      names(constant_rows) <- names(balance)
      constant_rows$Type <- 'Constant'
      constant_rows$variable <- constants
      balance <- rbind(balance, constant_rows)
    }
    list(status="ok", members=members, balance=balance,
         versions=list(MatchIt=as.character(packageVersion("MatchIt")),
                       cobalt=as.character(packageVersion("cobalt"))))
  } else {
    for(v in unlist(request$categorical)) input[[v]] <- factor(input[[v]])
    predictors <- unlist(request$terms)
    if(mode == "conditional_reference") {
      suppressPackageStartupMessages(library(survival))
      fit <- clogit(reformulate(c(predictors,"strata(match_set_id)"), response="is_case"),
                    data=input, method="exact", control=coxph.control(iter.max=request$max_iterations))
      result <- list(status="ok", coefficients=as.list(coef(fit)),
                     se=as.list(sqrt(diag(vcov(fit)))), version=as.character(packageVersion("survival")))
    } else if(mode == "firth") {
      suppressPackageStartupMessages(library(logistf))
      fit <- logistf(reformulate(predictors, response="is_case"), data=input, pl=TRUE,
                    control=logistf.control(maxit=request$max_iterations),
                    plcontrol=logistpl.control(maxit=request$max_iterations))
      result <- list(status="ok", coefficients=as.list(coef(fit)),
                    lower=as.list(fit$ci.lower), upper=as.list(fit$ci.upper), p=as.list(fit$prob),
                    convergence=unname(fit$conv), converged=all(abs(fit$conv) <= c(1e-5, 1e-5, 1e-5)),
                    iterations=unname(fit$iter),
                    version=as.character(packageVersion("logistf")))
    } else stop("Unknown engine mode")
    result
  }
}, error=function(e) list(status="error", message=conditionMessage(e)))
loaded <- sort(loadedNamespaces())
result$runtime <- list(R=R.version.string,
  packages=setNames(lapply(loaded, function(p) as.character(packageVersion(p))), loaded))
write_json(result, output, auto_unbox=TRUE, digits=NA, na="null", null="null")
if(result$status != "ok") quit(status=1)
