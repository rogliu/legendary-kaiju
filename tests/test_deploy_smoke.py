import pathlib
import re
import stat
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent


def test_runner_help_exit_zero():
    r = subprocess.run([sys.executable, "-m", "kaiju.runner", "--help"],
                        capture_output=True, text=True, cwd=ROOT)
    assert r.returncode == 0
    out = r.stdout.lower()
    assert "run" in out and "settle" in out and "retrain" in out


def test_subcommands_help_exit_zero():
    for sub in ("run", "settle", "retrain"):
        r = subprocess.run([sys.executable, "-m", "kaiju.runner", sub, "--help"],
                            capture_output=True, text=True, cwd=ROOT)
        assert r.returncode == 0, f"{sub} --help failed: {r.stderr}"


def test_deploy_artifacts_exist_and_wrapper_executable():
    df = ROOT / "Dockerfile"
    sh = ROOT / "deploy" / "run_daily.sh"
    pl = ROOT / "deploy" / "com.kaiju.daily.plist"
    assert df.is_file() and sh.is_file() and pl.is_file()
    # wrapper must be executable
    assert sh.stat().st_mode & stat.S_IXUSR, "run_daily.sh not executable"
    # Dockerfile must NOT copy .env (no secret baked into image)
    dft = df.read_text()
    # no COPY/ADD of .env or the whole build context (would bake the plaintext key)
    assert not re.search(r'(?im)^\s*(COPY|ADD)\s+\.env\b', dft), "Dockerfile copies .env"
    assert not re.search(r'(?im)^\s*(COPY|ADD)\s+\.(\s|/)', dft), "Dockerfile copies whole context"
    di = (ROOT / ".dockerignore")
    assert di.is_file() and ".env" in di.read_text(), ".dockerignore missing or doesn't exclude .env"
    assert "kaiju.runner" in dft
    # wrapper invokes settle, retrain, run
    sht = sh.read_text()
    assert "settle" in sht and "retrain" in sht and "run" in sht
    # plist is valid-ish XML referencing the wrapper
    plt = pl.read_text()
    assert "com.kaiju.daily" in plt and "run_daily.sh" in plt and "<plist" in plt
