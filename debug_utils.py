import logging
import os


def env_flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


DEBUG_ENABLED = env_flag("COMFYUI_SUBWORKFLOW_DEBUG", False)


def configure_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG if DEBUG_ENABLED else logging.INFO)
    return logger
