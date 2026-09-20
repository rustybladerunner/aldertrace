"""Read-only, offline integrity and metric replay for Aldertrace experiment v002.

Install at experiments/v002/reproduce.py. Default execution needs only Python's
standard library. The optional tokenizer environment must already exist.
"""
import argparse
import copy
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import sysconfig


EXPORT = "experiments/v002/EXPORT-MANIFEST.json"
CAMPAIGN = "experiments/v002/evidence/campaign"
FROZEN = CAMPAIGN + "/v002-frozen"
REPORTS = (
    ("v002-development-cloud-001-report-final", "v002-development-cloud-001", "development"),
    ("v002-development-cloud-002-report", "v002-development-cloud-002", "development"),
    ("v002-development-cloud-003-report", "v002-development-cloud-003", "development"),
    ("v002-development-local-002-report", "v002-development-local-002", "development"),
    ("v002-calibration-report", "v002-frozen/calibration", "calibration"),
    ("v002-test-report", "v002-frozen/test", "test"),
)


class ReproductionError(Exception):
    """A concrete integrity, compatibility, or replay mismatch."""


def strict_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ReproductionError("duplicate JSON object key")
        result[key] = value
    return result


def read_json(path):
    def invalid_constant(value):
        raise ReproductionError("non-finite JSON number")
    return json.loads(path.read_text(encoding="utf8"),
                      object_pairs_hook=strict_object, parse_constant=invalid_constant)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def contained(base, name):
    # These inventories intentionally use portable, repository-relative names.
    if not isinstance(name, str) or "\\" in name or ":" in name:
        raise ReproductionError("non-portable inventory path")
    relative = PurePosixPath(name)
    if relative.is_absolute() or not relative.parts or any(p in (".", "..") for p in name.split("/")):
        raise ReproductionError("unsafe inventory path")
    resolved = base.joinpath(*relative.parts).resolve()
    if not resolved.is_relative_to(base.resolve()):
        raise ReproductionError("inventory path escapes its root")
    return resolved


def verify_entries(base, entries, title):
    if not isinstance(entries, dict) or not entries:
        raise ReproductionError(title + ": empty or invalid inventory")
    for name, expected in entries.items():
        if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise ReproductionError(title + ": invalid SHA-256")
        path = contained(base, name)
        if not path.is_file() or sha(path) != expected:
            raise ReproductionError(title + ": missing or changed file: " + name)
    return len(entries)


def verify_dataset(root, manifest_name, original=False):
    manifest = read_json(root / manifest_name)
    entries = manifest.get("assets", {})
    count = verify_entries(root, entries, manifest_name)
    names = set()
    for path in root.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
            continue
        if original and ("results" in path.parts or path.name == "manifest.json"):
            continue
        if not original and path == root / manifest_name:
            continue
        names.add(path.relative_to(root).as_posix())
    if names != set(entries):
        raise ReproductionError(manifest_name + ": dataset inventory membership differs")
    return count, entries


def verify_integrity(repo):
    export = read_json(repo / EXPORT)
    export_count = verify_entries(repo, export.get("files", {}), "export")
    if export_count != 95:
        raise ReproductionError("v002 export must contain exactly 95 file hashes")
    original_count, _ = verify_dataset(repo / "study", "manifest.json", original=True)
    v2_count, v2_entries = verify_dataset(repo / "study-v2", "MANIFEST.json")
    freeze = read_json(repo / FROZEN / "freeze.json")
    if freeze.get("dataset_relative") != "study-v2" or freeze.get("dataset_assets") != v2_entries:
        raise ReproductionError("freeze differs from the study-v2 dataset inventory")
    implementation = freeze.get("implementation_assets", {})
    implementation_count = verify_entries(repo, implementation, "frozen implementation")
    current = {p.relative_to(repo).as_posix() for folder in ("study-execution", "logitpick")
               for p in (repo / folder).glob("*.py")
               if p.name not in ("memory_ablation.py", "test_memory_ablation.py")}
    current.update(("study/core.py", "EVALUATION_PROTOCOL.md"))
    if current != set(implementation):
        raise ReproductionError("frozen implementation inventory membership differs")
    return {"export_files": export_count, "original_study_assets": original_count,
            "study_v2_assets": v2_count, "frozen_implementation_assets": implementation_count}, freeze


def offline_read_only_guard(event, args):
    """Defense against accidental side effects, not a malicious-code sandbox."""
    if event.startswith(("socket.", "subprocess.", "os.exec", "os.spawn", "os.posix_spawn")):
        raise ReproductionError("offline replay blocked network or process dispatch: " + event)
    if event in ("os.system", "os.startfile", "os.remove", "os.rename", "os.rmdir", "os.mkdir",
                 "os.truncate", "os.link", "os.symlink", "os.chmod", "os.chown", "os.utime",
                 "shutil.copyfile", "shutil.copymode", "shutil.copystat", "shutil.rmtree"):
        raise ReproductionError("read-only replay blocked filesystem or process mutation")
    if event == "open":
        mode = args[1] if len(args) > 1 else None
        flags = args[2] if len(args) > 2 else 0
        write_flags = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        if (isinstance(mode, str) and any(c in mode for c in "wax+")) or (isinstance(flags, int) and flags & write_flags):
            raise ReproductionError("read-only replay blocked opening a file for writing")


def checked_import(name, repo):
    module = importlib.import_module(name)
    expected = repo / "study-execution" / (name + ".py")
    if Path(module.__file__).resolve() != expected.resolve():
        raise ReproductionError("replay module resolved outside the selected checkout")
    return module


def comparison_view(value, with_tokens):
    result = copy.deepcopy(value)
    if not with_tokens:
        result.pop("tokenizer_provenance", None)
        for arm in result["arms"].values():
            arm.pop("input_proxy", None)
    elif result.get("tokenizer_provenance"):
        # The frozen binary/tokenizer identity is checked by FrozenTokenizer.
        # CPython patch version is host provenance, not a measured outcome.
        result["tokenizer_provenance"].pop("runtime_python", None)
    return result


def compare_report(actual, saved, with_tokens, name):
    left, right = comparison_view(actual, with_tokens), comparison_view(saved, with_tokens)
    if left != right:
        # Name changed top-level categories, never print case content or labels.
        changed = sorted(k for k in set(left) | set(right) if left.get(k) != right.get(k))
        raise ReproductionError(name + ": recomputed report differs in " + ", ".join(changed))


def aggregate_report(name, report):
    arms = {}
    for arm, value in report["arms"].items():
        arms[arm] = {key: value[key] for key in (
            "primary_observed_n", "primary_missing_n", "invalid_primary_n", "primary_latency",
            "resources_all_attempts", "unresolved_attempts", "retries", "repeat_stability")}
        arms[arm]["raw"] = value["raw"]["overall"]
        arms[arm]["enforced"] = value["enforced"]["overall"]
        if value.get("input_proxy") is not None:
            arms[arm]["input_proxy"] = value["input_proxy"]["primary_including_retries"]
    return {"report": name, "split": report["split"], "unique_planned": report["n_unique_planned"],
            "complete_from_evidence": report["complete_from_evidence"], "matches_saved_report": True,
            "arms": arms}


def reproduce(repo, tokenizer_environment=None, hashes_only=False):
    integrity, freeze = verify_integrity(repo)
    output = {"status": "verified", "integrity": integrity,
              "live_calls": 0, "network_calls": 0, "evidence_files_written": 0}
    if hashes_only:
        output.update({"scope": "integrity only; metrics not replayed", "reports_replayed": 0})
        return output
    if os.name != "nt":
        raise ReproductionError("full frozen phase replay requires Windows: threshold journal paths contain "
                                "Windows backslashes; use --hashes-only for portable integrity verification")
    if tokenizer_environment is not None:
        if sys.version_info[:2] != (3, 12) or sysconfig.get_platform() != "win-amd64":
            raise ReproductionError("the frozen optional tokenizer requires CPython 3.12 on Windows amd64")
    sys.path.insert(0, str(repo / "study-execution"))
    experiment = checked_import("experiment_v2", repo)
    experiment.verify(repo / FROZEN)
    reporter = checked_import("development_report", repo)
    reports = []
    for name, run, phase in REPORTS:
        saved = read_json(repo / "experiments/v002/reports" / name / "report.json")
        actual = reporter.report(repo / CAMPAIGN / run, dataset=repo / "study-v2" / (phase + ".json"),
                                 tokenizer_environment=tokenizer_environment)
        compare_report(actual, saved, tokenizer_environment is not None, name)
        reports.append(aggregate_report(name, actual))
    # Rehash after all replay work. No source/evidence mutation is accepted.
    final_integrity, _ = verify_integrity(repo)
    if integrity != final_integrity:
        raise ReproductionError("integrity changed during replay")
    complete = sum(r["complete_from_evidence"] for r in reports)
    output.update({"scope": "independent raw-journal replay and saved-report comparison",
                   "experiment_v2_verify": "passed", "reports_replayed": len(reports),
                   "reports_complete": complete, "reports_incomplete": len(reports) - complete,
                   "unavailable_arm": freeze["settings"].get("local_status"),
                   "input_proxy_recomputed": tokenizer_environment is not None,
                   "reports": reports,
                   "limitations": ["Synthetic agent-authored labels have provisional separate-agent review and no human adjudication.",
                       "Replay checks arithmetic and recorded evidence, not independent evaluator correctness.",
                       "Full-task success, actual net downstream tokens and baseline execution latency remain unknown.",
                       "Without --tokenizer-environment the saved input proxies are hash-verified only.",
                       "Full phase replay preserves the original Windows-only frozen path semantics."]})
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[2],
                        help="checkout root; inferred when installed at experiments/v002/reproduce.py")
    parser.add_argument("--hashes-only", action="store_true", help="portable integrity verification without metric replay")
    parser.add_argument("--tokenizer-environment", type=Path, help="existing frozen tokenizer environment; never installs anything")
    args = parser.parse_args()
    sys.dont_write_bytecode = True
    sys.addaudithook(offline_read_only_guard)
    try:
        value = reproduce(args.repo.resolve(), args.tokenizer_environment, args.hashes_only)
    except (ReproductionError, OSError, ValueError, KeyError, ImportError) as error:
        print(json.dumps({"status": "failed", "reason": str(error), "live_calls": 0}, sort_keys=True))
        return 1
    print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
