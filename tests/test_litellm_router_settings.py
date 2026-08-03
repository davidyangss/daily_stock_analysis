from pathlib import Path

from src.config import Config, get_litellm_router_kwargs


def test_parse_litellm_router_settings(tmp_path: Path) -> None:
    config_path = tmp_path / "litellm.yaml"
    config_path.write_text(
        """
model_list: []
router_settings:
  routing_strategy: least-busy
  num_retries: 1
  timeout: 5
  allowed_fails: 3
  cooldown_time: 60
""",
        encoding="utf-8",
    )

    settings = Config._parse_litellm_router_settings(str(config_path))

    assert settings == {
        "routing_strategy": "least-busy",
        "num_retries": 1,
        "timeout": 5,
        "allowed_fails": 3,
        "cooldown_time": 60,
    }


def test_invalid_litellm_router_settings_keep_legacy_defaults(tmp_path: Path) -> None:
    config_path = tmp_path / "litellm.yaml"
    config_path.write_text(
        """
router_settings:
  routing_strategy: ''
  num_retries: -1
""",
        encoding="utf-8",
    )

    config = Config(
        litellm_router_settings=Config._parse_litellm_router_settings(str(config_path))
    )

    assert get_litellm_router_kwargs(config) == {
        "routing_strategy": "simple-shuffle",
        "num_retries": 2,
    }
