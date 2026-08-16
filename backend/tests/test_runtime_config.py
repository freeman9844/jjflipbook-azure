import logging
from unittest.mock import patch

import pytest

import main
from utils import required_setting, validate_runtime_config


def test_production_rejects_missing_required_settings():
    with patch.dict(
        "os.environ",
        {"APP_ENV": "production"},
        clear=True,
    ):
        with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
            validate_runtime_config()


def test_production_rejects_legacy_defaults():
    with patch.dict(
        "os.environ",
        {
            "APP_ENV": "production",
            "ADMIN_PASSWORD": "admin",
            "INTERNAL_API_KEY": "secret_dev_key",
        },
        clear=True,
    ):
        with pytest.raises(RuntimeError, match="ADMIN_PASSWORD"):
            validate_runtime_config()


def test_test_environment_allows_explicit_development_defaults():
    with patch.dict("os.environ", {"APP_ENV": "test"}, clear=True):
        assert required_setting("INTERNAL_API_KEY", "secret_dev_key") == "secret_dev_key"


def test_azure_sdk_logging_is_warning_or_higher():
    main.configure_logging()
    assert logging.getLogger("azure").level == logging.WARNING
