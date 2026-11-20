from cpd import config


def test_rutas_cuelgan_de_la_raiz():
    assert (config.RAIZ / "pyproject.toml").exists()
    assert config.RAW_DIR.parent == config.DATA_DIR
    assert config.WAREHOUSE_PATH.suffix == ".duckdb"


def test_asegurar_directorios_crea_carpetas(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(config, "PROCESSED_DIR", tmp_path / "processed")
    monkeypatch.setattr(config, "WAREHOUSE_DIR", tmp_path / "warehouse")
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path / "models")
    monkeypatch.setattr(config, "FIGURES_DIR", tmp_path / "figures")
    config.asegurar_directorios()
    assert all((tmp_path / d).is_dir() for d in ("raw", "processed", "warehouse", "models"))
