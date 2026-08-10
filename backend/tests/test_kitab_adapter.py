"""Phase 1B §7C — the KITAB-Bench adapter must refuse to run without an explicit
license acknowledgement and a real local path (no auto-download, no vendoring)."""
import pytest

from benchmarks import kitab_adapter as K


def test_refuses_without_license_ack():
    with pytest.raises(K.LicenseNotAcknowledged):
        K.load_kitab_ocr("/whatever", acknowledge_license=False)


def test_refuses_missing_path_even_with_ack():
    with pytest.raises(FileNotFoundError):
        K.load_kitab_ocr("/nonexistent/kitab/split", acknowledge_license=True)


def test_cli_refuses_without_ack(capsys):
    rc = K.main(["--path", "/nonexistent", "--limit", "1"])
    assert rc == 2
    assert "REFUSED" in capsys.readouterr().err
