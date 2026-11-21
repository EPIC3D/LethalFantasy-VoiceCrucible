"""Tests for the installer helpers: GPU verdicts, download list, redaction, signed updates and rollback."""

import base64
import io
import socket
import zipfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from voicecrucible.installer import diagnose, gpucheck, manifest, update


def _gpu(name, driver="621.14", mb=8188, cc=8.9):
    return {"name": name, "driver": driver, "vram_mb": mb, "compute": cc}


def test_gpu_verdicts():
    assert gpucheck.evaluate([_gpu("RTX 40xx")], []).supported
    assert "no bf16" in gpucheck.evaluate([_gpu("RTX 2060", cc=7.5, mb=6144)], []).notes[0]
    assert not gpucheck.evaluate([_gpu("GTX 1080", cc=6.1)], []).supported
    old = gpucheck.evaluate([_gpu("RTX 3060", driver="537.42")], [])
    assert not old.supported and "570" in old.notes[0]
    amd = gpucheck.evaluate([], ["AMD Radeon RX 7800 XT"])
    assert not amd.supported and "experimental" in amd.notes[0]


def test_manifest_adds_dependencies_and_totals():
    comps = manifest.load()
    keys = [c.key for c in manifest.resolve(comps, {"chatterbox"})]
    assert keys == ["base", "gpu", "chatterbox"]
    assert "TOTAL" in manifest.table(manifest.resolve(comps, {"qwen", "seedvc"}))
    with pytest.raises(ValueError):
        manifest.resolve(comps, {"nope"})


def test_redact_removes_personal_data(tmp_path):
    text = f"paired from 192.168.1.20 by {socket.gethostname()} token=abc123 at C:\\Users\\x"
    out = diagnose.redact(text)
    assert "192.168" not in out and socket.gethostname() not in out and "abc123" not in out


def _signed_zip(files: dict[str, str]):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    key = Ed25519PrivateKey.generate()
    pub = base64.b64encode(key.public_key().public_bytes(serialization.Encoding.Raw,
                                                         serialization.PublicFormat.Raw)).decode()
    return buf.getvalue(), base64.b64encode(key.sign(buf.getvalue())).decode(), pub


def test_signature_is_required_and_checked():
    data, sig, pub = _signed_zip({"a.txt": "x"})
    update.verify(data, sig, pub)
    with pytest.raises(update.UpdateError, match="not valid"):
        update.verify(data + b"tampered", sig, pub)
    with pytest.raises(update.UpdateError, match="no update key"):
        update.verify(data, sig, "")


def test_built_in_public_key_is_valid():
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    Ed25519PublicKey.from_public_bytes(base64.b64decode(update.PUBLIC_KEY))


def test_tag_names_become_program_versions():
    assert update.tag_to_version("v0.1.0-beta.1") == "0.1.0b1"
    assert update.tag_to_version("v0.2.0-rc.2") == "0.2.0rc2" and update.tag_to_version("v1.0.0") == "1.0.0"
    assert not update.is_newer("0.1.0b1", "0.1.0b1") and update.is_newer("0.1.0b2", "0.1.0b1")


def test_downgrade_is_refused():
    newer, _, _ = _signed_zip({"voicecrucible/__init__.py": '__version__ = "0.2.0"\n'})
    older, _, _ = _signed_zip({"voicecrucible/__init__.py": '__version__ = "0.1.0b1"\n'})
    assert update.check_newer(newer, "0.1.0") == "0.2.0"
    with pytest.raises(update.UpdateError, match="not newer"):
        update.check_newer(older, "0.1.0")
    assert update._version_tuple("0.1.0b2") < update._version_tuple("0.1.0") < update._version_tuple("0.1.1")


def test_install_keeps_user_data_and_rollback_restores(tmp_path):
    (tmp_path / "app.py").write_text("old")
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "identity.json").write_text("pairing")
    (tmp_path / "profiles" / "lf" / "voices").mkdir(parents=True)
    (tmp_path / "profiles" / "lf" / "voices" / "Mira.wav").write_text("voice")
    data, _, _ = _signed_zip({"VoiceCrucible/voicecrucible/__init__.py": '__version__ = "9.0.0"\n',
                              "VoiceCrucible/app.py": "new", "VoiceCrucible/profiles/lf/characters.json": "{}",
                              "VoiceCrucible/profiles/template/x.json": "t", "VoiceCrucible/work/evil.txt": "no",
                              "VoiceCrucible/../outside.txt": "no"})
    assert update.zip_version(data) == "9.0.0"  # release zips have one top folder
    update.install(data, tmp_path)
    assert (tmp_path / "app.py").read_text() == "new"
    assert (tmp_path / "profiles" / "template" / "x.json").read_text() == "t"  # template is updated
    assert not (tmp_path / "profiles" / "lf" / "characters.json").exists()  # installed profiles are not
    assert (tmp_path / "work" / "identity.json").read_text() == "pairing" and not (tmp_path / "work" / "evil.txt").exists()
    assert (tmp_path / "profiles" / "lf" / "voices" / "Mira.wav").read_text() == "voice"
    assert not (tmp_path.parent / "outside.txt").exists()
    update.rollback(tmp_path)
    assert (tmp_path / "app.py").read_text() == "old" and not (tmp_path / "previous").exists()


def test_new_profile_from_template(tmp_path):
    import shutil
    from voicecrucible.installer import profiles
    shutil.copytree(Path(__file__).parents[1] / "profiles" / "template", tmp_path / "profiles" / "template")
    target = profiles.new_profile("mygame", tmp_path)
    assert (target / "voices" / "chatterbox").is_dir()
    assert '"name": "mygame"' in (target / "profile.json").read_text()
    assert "CharacterA" not in (target / "characters.json").read_text()  # speakers come from the export
    with pytest.raises(profiles.ProfileError, match="already exists"):
        profiles.new_profile("mygame", tmp_path)


def test_profile_pack_install_update_and_backup(tmp_path):
    from voicecrucible.installer import profiles
    src = Path(__file__).parent / "data" / "profile"

    def pack(version: str, extra: dict | None = None) -> Path:
        out = tmp_path / f"pack_{version}.zip"
        with zipfile.ZipFile(out, "w") as z:
            for f in src.rglob("*"):
                if f.is_file() and f.suffix != ".wav":
                    text = f.read_text(encoding="utf-8")
                    if f.name == "profile.json":
                        text = text.replace('"1.0.0"', f'"{version}"')
                    z.writestr(f"testgame/{f.relative_to(src).as_posix()}", text)
            for name, text in (extra or {}).items():
                z.writestr(f"testgame/{name}", text)
        return out

    meta, backup = profiles.install(pack("1.0.0", {"voices/chatterbox/Mira.wav": "v1"}), tmp_path)
    assert meta["name"] == "testgame" and backup is None
    target = tmp_path / "profiles" / "testgame"
    (target / "characters.json").write_text("{\"my\": \"change\"}")
    meta, backup = profiles.install(pack("1.1.0"), tmp_path)  # new pack without voices
    assert meta["version"] == "1.1.0" and (backup / "characters.json").read_text() == "{\"my\": \"change\"}"
    assert (target / "voices" / "chatterbox" / "Mira.wav").read_text() == "v1"  # voices kept
    assert [p["folder"] for p in profiles.installed(tmp_path)] == ["testgame"]
    bad = tmp_path / "bad.zip"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("x/readme.txt", "no profile")
    with pytest.raises(profiles.ProfileError, match="missing"):
        profiles.install(bad, tmp_path)
