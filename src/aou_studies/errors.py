class StudyError(ValueError):
    """An invalid or unsupported study cannot safely proceed."""


class ContextError(StudyError):
    """Choose or repair a dataset/workspace context."""


class DataContractError(StudyError):
    """Source data violate an explicit grain, type or membership contract."""


class EngineError(RuntimeError):
    """An external engine is unavailable or did not complete its contract."""
