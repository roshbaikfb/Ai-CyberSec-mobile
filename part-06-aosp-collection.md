[← الجزء الخامس](./part-05-research-environment.md) · [الفهرس](./README.md)

# الجزء السادس: جمع AOSP

## الفصل 13: تنزيل AOSP

### 13.1 repo tool مقابل git clone مباشر

| الطريقة | الميزة | العيب | القرار هنا |
|---|---|---|---|
| `repo` tool الرسمي | يجلب المشروع الكامل بكل المستودعات الفرعية المتزامنة بدقة | ثقيل جدًا (مئات الجيجابايت)، غير عملي لمشروعنا الذي يركّز على `frameworks/base` فقط | ❌ لا نستخدمه كخطوة أولى |
| `git clone` لمستودع فردي | نجلب فقط `frameworks/base` (وما نحتاجه لاحقًا) عبر Git مباشرة من مرآة AOSP على Git | نفقد التزامن الدقيق بين كل المشاريع الفرعية | ✅ الخيار العملي لبيئة 32GB RAM / تخزين محدود |

نستخدم `git clone` لكل مستودع على حدة، ونعتمد على **tags** الرسمية (مثل `android-14.0.0_r1`) لتثبيت نقطة زمنية دقيقة بدل الاعتماد على أحدث حالة لـ`branch` متحرك.

### 13.2 الفرق بين tags وbranches وrelease history

- **Tags:** نقاط ثابتة تمثّل إصدارًا فعليًا صدر للمستخدمين (الأكثر فائدة لمشروعنا — نعرف بالضبط أي كود كان في الإنتاج).
- **Branches:** خطوط تطوير متحركة (مثل `main` أو `android14-dev`) — مفيدة لمتابعة أحدث تغييرات لكنها غير مستقرة كمرجع تاريخي.
- **Release history:** تسلسل الإصدارات عبر الزمن — نحتاجه لتفعيل الفصل 37 (Future Patch Evaluation) لاحقًا، حيث ندرّب على إصدارات أقدم ونختبر على إصدارات أحدث لم يرها النموذج إطلاقًا.

### 13.3 سكريبت الجلب (`collector/fetch_aosp.py`)

```python
# collector/fetch_aosp.py
"""
يجلب نسخًا محددة من frameworks/base عبر إصدارات Android متعددة،
مع الحفاظ على تاريخ commits الكامل لكل نسخة (لا shallow clone)
لأن الفصل 15 (Patch Mining) يحتاج التاريخ الكامل.
"""
import subprocess
import json
from pathlib import Path
from dataclasses import dataclass, asdict

AOSP_MIRROR = "https://android.googlesource.com/platform/frameworks/base"

TARGET_VERSIONS = {
    "android-12": "android-12.0.0_r34",
    "android-13": "android-13.0.0_r75",
    "android-14": "android-14.0.0_r41",
    "android-15": "android-15.0.0_r10",
    "android-16": "android-16.0.0_r1",
    "main": "main",
}

DATA_ROOT = Path("aosp_sources")

@dataclass
class FetchResult:
    version_label: str
    ref: str
    local_path: str
    head_commit: str
    fetched_at: str

def run(cmd: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, check=True
    )
    return result.stdout.strip()

def fetch_version(label: str, ref: str) -> FetchResult:
    target_dir = DATA_ROOT / label
    target_dir.parent.mkdir(parents=True, exist_ok=True)

    if not target_dir.exists():
        print(f"[{label}] cloning full history (this can take a while)...")
        run([
            "git", "clone", AOSP_MIRROR, str(target_dir)
        ])
    else:
        print(f"[{label}] already exists, fetching updates...")
        run(["git", "fetch", "--all", "--tags"], cwd=target_dir)

    run(["git", "checkout", ref], cwd=target_dir)
    head = run(["git", "rev-parse", "HEAD"], cwd=target_dir)

    from datetime import datetime, timezone
    return FetchResult(
        version_label=label,
        ref=ref,
        local_path=str(target_dir),
        head_commit=head,
        fetched_at=datetime.now(timezone.utc).isoformat(),
    )

def main():
    results = []
    for label, ref in TARGET_VERSIONS.items():
        try:
            r = fetch_version(label, ref)
            results.append(asdict(r))
            print(f"[{label}] OK -> {r.head_commit[:12]}")
        except subprocess.CalledProcessError as e:
            print(f"[{label}] FAILED: {e.stderr}")

    manifest_path = DATA_ROOT / "fetch_manifest.json"
    manifest_path.write_text(json.dumps(results, indent=2, ensure_ascii=False))
    print(f"\nManifest written to {manifest_path}")

if __name__ == "__main__":
    main()
```

> **ملاحظة على أرقام الإصدارات:** أرقام `_rXX` في `TARGET_VERSIONS` تتغير باستمرار مع كل إصدار جديد من AOSP. لا تعتمد على الأرقام أعلاه حرفيًا — استخرج أحدث tag فعلي لكل فرع عبر: `git ls-remote --tags <mirror-url> | grep android-14` قبل التشغيل، وحدّث القاموس تبعًا لذلك.

### 13.4 تشغيل الجلب

```bash
cd ~/android-vuln-llm
python collector/fetch_aosp.py
```

توقّع أن تستهلك هذه الخطوة عدة ساعات ومساحة قرص كبيرة (كل نسخة كاملة بتاريخها قد تتجاوز عدة جيجابايت) — لهذا نجلب فقط `frameworks/base` كنقطة بداية، ونضيف مستودعات أخرى (الفصل 4.2) عند الحاجة الفعلية فقط.

---

## الفصل 14: Repository Metadata

كل ملف كود سنعالجه لاحقًا يجب أن يحمل معه سياقًا كاملًا عن مصدره — بدون هذا، أي Sample في الـDataset لاحقًا يفقد قابلية التتبّع (traceability)، وهو شرط أساسي لمنع الـData Leakage (الفصل 36).

### 14.1 Schema

```json
{
  "project": "frameworks/base",
  "branch": "android-14",
  "tag": "android-14.0.0_r41",
  "commit": "a1b2c3d4e5f6...",
  "parent_commit": "f6e5d4c3b2a1...",
  "path": "services/core/java/com/android/server/pm/PackageManagerService.java",
  "language": "java",
  "timestamp": "2024-03-12T10:15:00Z"
}
```

### 14.2 استخراج Metadata فعليًا (`collector/extract_file_metadata.py`)

```python
# collector/extract_file_metadata.py
import subprocess
from pathlib import Path
from dataclasses import dataclass, asdict
import json

@dataclass
class FileMetadata:
    project: str
    branch: str
    tag: str
    commit: str
    parent_commit: str
    path: str
    language: str
    timestamp: str

def run(cmd: list[str], cwd: Path) -> str:
    return subprocess.run(
        cmd, cwd=cwd, capture_output=True, text=True, check=True
    ).stdout.strip()

def detect_language(path: str) -> str:
    if path.endswith(".java"):
        return "java"
    if path.endswith(".kt"):
        return "kotlin"
    if path.endswith(".aidl"):
        return "aidl"
    return "unknown"

def extract_for_file(repo_path: Path, file_rel_path: str,
                      branch: str, tag: str) -> FileMetadata:
    commit = run(["git", "rev-parse", "HEAD"], cwd=repo_path)
    parent = run(["git", "rev-parse", "HEAD^"], cwd=repo_path)
    timestamp = run(
        ["git", "log", "-1", "--format=%cI", "--", file_rel_path],
        cwd=repo_path
    )
    return FileMetadata(
        project="frameworks/base",
        branch=branch,
        tag=tag,
        commit=commit,
        parent_commit=parent,
        path=file_rel_path,
        language=detect_language(file_rel_path),
        timestamp=timestamp,
    )

def extract_for_directory(repo_path: Path, subdir: str,
                           branch: str, tag: str) -> list[dict]:
    target = repo_path / subdir
    results = []
    for f in target.rglob("*"):
        if f.suffix not in (".java", ".kt", ".aidl"):
            continue
        rel = str(f.relative_to(repo_path))
        try:
            meta = extract_for_file(repo_path, rel, branch, tag)
            results.append(asdict(meta))
        except subprocess.CalledProcessError:
            continue
    return results

if __name__ == "__main__":
    repo = Path("aosp_sources/android-14")
    metas = extract_for_directory(
        repo, "services/core/java/com/android/server",
        branch="android-14", tag="android-14.0.0_r41"
    )
    out = Path("collector/output/android-14_metadata.jsonl")
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as f:
        for m in metas:
            f.write(json.dumps(m, ensure_ascii=False) + "\n")
    print(f"Wrote {len(metas)} file records to {out}")
```

> **ملاحظة أداء:** استدعاء `git log` لكل ملف على حدة بطيء على آلاف الملفات. هذا مقبول لمرحلة v0.1 (MVP)، لكن في الفصل 34 (PostgreSQL Schema) سننقل هذا التتبّع لقاعدة بيانات مع فهرسة (`index`) على `commit` بدل استدعاءات Git متكررة.

> **Definition of Done — الجزء السادس:** يوجد على الأقل نسخة كاملة من `frameworks/base` لإصدارين مختلفين (مثلًا android-13 وandroid-14) على القرص، مع ملف `fetch_manifest.json` صالح، وملف metadata JSONL واحد على الأقل ناتج عن `extract_file_metadata.py` يحتوي حقول كاملة بدون قيم فارغة.

---

[← الجزء الخامس](./part-05-research-environment.md) · [الفهرس](./README.md) · [الجزء السابع →](./part-07-patch-mining.md)
