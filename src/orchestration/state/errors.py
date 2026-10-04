class PlanValidationError(ValueError):
    """A task plan is empty or inconsistent.

    The message names the task and the problem. It does not include task inputs.
    """


class StateUpdateError(ValueError):
    """A state update was partial, invalid, or past a limit.

    The message names the field and the error type. It does not include values.
    """
