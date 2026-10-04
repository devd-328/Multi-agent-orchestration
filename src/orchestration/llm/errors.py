class LLMError(Exception):
    """A model request failed.

    The message names the failure. It does not include the prompt, the model
    name, the URL, or response content.
    """
